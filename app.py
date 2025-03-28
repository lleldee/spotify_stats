from flask import Flask, render_template, redirect, url_for, session, request, flash, jsonify  
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
import spotipy
import os
import time
import random
from statistics import mean
import traceback
from peewee import *
from werkzeug.utils import secure_filename
import pandas as pd

load_dotenv()

# Datu baze

db = SqliteDatabase('spotify_stats.db')

class BaseModel(Model):
    class Meta:
        database = db

class User(BaseModel):
    spotify_id = CharField(unique=True)
    last_login = DateTimeField()

class TrackFeatures(BaseModel):
    user = ForeignKeyField(User, backref='tracks')
    danceability = FloatField()
    energy = FloatField()
    valence = FloatField()
    acousticness = FloatField()
    instrumentalness = FloatField()
    liveness = FloatField()
    speechiness = FloatField()
    created_at = DateTimeField()

def create_tables():
    with db:
        db.create_tables([User, TrackFeatures])

create_tables()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')

# Spotify lietinas
SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
SPOTIFY_REDIRECT_URI = 'http://127.0.0.1:5000/callback'

def create_spotify_oauth():
    return SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope="user-top-read user-read-recently-played user-library-read user-read-private user-read-email user-read-playback-state"
    )

@app.route('/')
def home():
    return render_template('index.html')

def get_token():
    token_info = session.get('token_info')
    if not token_info or not token_info.get('access_token'):
        return None
    
    
    if time.time() > token_info['expires_at'] - 60:  
        sp_oauth = create_spotify_oauth()
        try:
            new_token = sp_oauth.refresh_access_token(token_info['refresh_token'])
            session['token_info'] = new_token
        except Exception as e:
            print(f"Refresh failed: {str(e)}")
            return None
    
    return token_info

@app.route('/login')
def login():
    sp_oauth = create_spotify_oauth()
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)

@app.route('/callback')
def callback():
    sp_oauth = create_spotify_oauth()
    code = request.args.get('code')
    try:
        
        token_info = sp_oauth.get_access_token(code)
        session['token_info'] = token_info
        return redirect(url_for('game'))
    except Exception as e:
        print(f"Auth failed: {str(e)}")
        return redirect(url_for('home'))

@app.route('/game', methods=['GET', 'POST'])
def game():
    token_info = get_token()
    if not token_info:
        return redirect(url_for('login'))
    
    sp = spotipy.Spotify(auth=token_info['access_token'])

    if 'correct_tracks' not in session:
        top_tracks = sp.current_user_top_tracks(limit=10, time_range='medium_term')['items']
        session['correct_tracks'] = [track['name'].lower().strip() for track in top_tracks[:3]]
        session['attempts'] = 0
        session['show_answers'] = False

    if request.args.get('show_answers'):
        session['show_answers'] = True
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        session['attempts'] += 1
        guesses = [
            request.form['guess1'].lower().strip(),
            request.form['guess2'].lower().strip(),
            request.form['guess3'].lower().strip()
        ]
        correct_guesses = sum(1 for guess in guesses if guess in session['correct_tracks'])
        
        if correct_guesses == 3:
            session.pop('correct_tracks', None)
            session.pop('attempts', None)
            return redirect(url_for('dashboard', success=True))
        else:
            flash(f'You got {correct_guesses}/3 correct! Try again!')
            return redirect(url_for('game'))

    return render_template('game.html', attempts=session.get('attempts', 0))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/dashboard')
def dashboard():
    token_info = get_token()
    if not token_info:
        return redirect(url_for('login'))
    
    try:
        sp = spotipy.Spotify(auth=token_info['access_token'])
        
        # user info
        user_info = sp.current_user()
        
        avg_features = {
            'danceability': 0.5,
            'energy': 0.5,
            'valence': 0.5,
            'acousticness': 0.5,
            'instrumentalness': 0.5,
            'liveness': 0.5,
            'speechiness': 0.5
        }
        top_tracks = {'items': []}
        top_artists = {'items': []}

        try:
            # top tracks
            top_tracks = sp.current_user_top_tracks(limit=10, time_range='medium_term')
            
            # audio features if tracks exist
            if top_tracks['items']:
                track_ids = [track['id'] for track in top_tracks['items'] if track.get('id')]
                if track_ids:
                    audio_features = sp.audio_features(track_ids)
                    if audio_features and all(audio_features):
                        avg_features = {
                            'danceability': mean(f['danceability'] for f in audio_features if f),
                            'energy': mean(f['energy'] for f in audio_features if f),
                            'valence': mean(f['valence'] for f in audio_features if f),
                            'acousticness': mean(f['acousticness'] for f in audio_features if f),
                            'instrumentalness': mean(f['instrumentalness'] for f in audio_features if f),
                            'liveness': mean(f['liveness'] for f in audio_features if f),
                            'speechiness': mean(f['speechiness'] for f in audio_features if f)
                        }
        
            # top artists
            top_artists = sp.current_user_top_artists(limit=3, time_range='medium_term')
            print("TOP ARTISTS RAW RESPONSE:", top_artists)  # Debug line
    
            if not top_artists.get('items'):
                top_artists = sp.current_user_top_artists(limit=3, time_range='medium_term')
                print("FALLBACK TO medium_TERM:", top_artists)
        
        except Exception as e:
            print(f"Error getting top artists: {e}")
            top_artists = {'items': []} 

        return render_template(
            'dashboard.html',
            user=user_info,
            top_tracks=top_tracks['items'],
            top_artists=top_artists['items'],
            avg_features=avg_features,  
            success=request.args.get('success'),
            correct_answers=session.pop('correct_tracks', None) if session.get('show_answers') else None
        )
    
    except Exception as e:
        print(f"Complete failure: {str(e)}")
        return render_template('error.html', error="Failed to load dashboard data")

@app.route('/music-dna')
def music_dna():
    try:

        token_info = get_token()
        if not token_info:
            return jsonify({"error": "Not authenticated"}), 401
        
        try:
            sp = spotipy.Spotify(auth=token_info['access_token'])
            
            try:
                top_tracks = sp.current_user_top_tracks(limit=10, time_range='medium_term')
                tracks = top_tracks.get('items', [])
                if not tracks:
                    recent = sp.current_user_recently_played(limit=10)
                    tracks = [item['track'] for item in recent.get('items', [])]
                if not tracks:
                    saved = sp.current_user_saved_tracks(limit=10)
                    tracks = [item['track'] for item in saved.get('items', [])]
            except Exception as e:
                return jsonify({"error": f"Track fetch failed: {str(e)}"}), 500
            
            track_ids = [t['id'] for t in tracks if t and t.get('id')]
            if not track_ids:
                return jsonify({"error": "No valid tracks found"}), 404
            
            audio_features = []
            for i in range(0, len(track_ids), 50):
                batch = track_ids[i:i+50]
                try:
                    features_batch = sp.audio_features(batch)
                    audio_features.extend([f for f in features_batch if f])
                except Exception as e:
                    print(f"Skipped batch {i}: {str(e)}")
            
            def safe_mean(key, default=0.5):
                values = [f.get(key, default) for f in audio_features if f]
                return round(mean(values), 3) if values else default
            
            avg_features = {
                "danceability": safe_mean('danceability'),
                "energy": safe_mean('energy'),
                "valence": safe_mean('valence'),
                "acousticness": safe_mean('acousticness'),
                "instrumentalness": safe_mean('instrumentalness'),
                "liveness": safe_mean('liveness'),
                "speechiness": safe_mean('speechiness')
            }
            
            return jsonify(avg_features)
        
        except Exception as e:
            print(f"Music DNA Error: {traceback.format_exc()}")
            return jsonify({"error": "Server error processing data"}), 500
        
    except Exception as e:
        df = pd.read_csv('data/backup.csv')
        return jsonify(df.iloc[0].to_dict())

@app.route('/about')
def about():
    return render_template('about.html')

if __name__ == '__main__':
    app.run(debug=True)
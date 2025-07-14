import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import random

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.config['SECRET_KEY'] = 'your-secret-key'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

players, player_avatars, power_ups, battle_stats = {}, {}, {}, {}
question_streak, player_draw_results, connected_players = {}, {}, set()
game_started, current_round, max_rounds = False, 1, 10

QUESTIONS = [
    {'question': 'What is deforestation?', 'options': ['Cutting trees', 'Planting flowers', 'Saving animals', 'Recycling'], 'correct': 0, 'difficulty': 'easy'},
    {'question': 'Which gas increases due to deforestation?', 'options': ['Carbon Dioxide', 'Oxygen', 'Nitrogen', 'Helium'], 'correct': 0, 'difficulty': 'medium'},
    {'question': 'Which animal lives in forests?', 'options': ['Tiger', 'Shark', 'Penguin', 'Camel'], 'correct': 0, 'difficulty': 'easy'},
    {'question': 'Major cause of deforestation?', 'options': ['Logging', 'Wind Energy', 'Recycling', 'Solar power'], 'correct': 0, 'difficulty': 'medium'},
    {'question': 'Deforestation causes...', 'options': ['Habitat loss', 'More oxygen', 'Ocean pollution', 'Volcanoes'], 'correct': 0, 'difficulty': 'easy'},
    {'question': 'Forest products include...', 'options': ['Paper', 'Plastic', 'Metal', 'Glass'], 'correct': 0, 'difficulty': 'easy'}
]

PRIZES = ["Keychain", "Nothing", "Draw Again", "Pencil", "Cutlery"]
PRIZE_PROBS = [25, 25, 5, 25, 20]

@app.route('/')
def index(): return render_template('index.html')

@app.route('/quiz')
def quiz(): return render_template('quiz.html')

@app.route('/result')
def result(): return render_template('result.html')

@app.route('/waiting')
def waiting(): return render_template('waiting.html')

@socketio.on('connect')
def on_connect(): print(f"[CONNECT] {request.sid}")

@socketio.on('disconnect')
def on_disconnect(): print(f"[DISCONNECT] {request.sid}")

@socketio.on('join')
def on_join(data):
    global game_started
    name = data.get('name', '').strip()
    password = data.get('password', '').strip()

    if not name or not password:
        emit('error', {'message': 'Name and password required'})
        return
    if len(players) >= 3:
        emit('error', {'message': 'Game full'})
        return
    if name in players:
        emit('error', {'message': f'Name "{name}" already taken'})
        return

    avatars = ["🦊", "🐸", "🦉", "🐯", "🦔", "🐰"]
    available = [a for a in avatars if a not in player_avatars.values()]
    selected_avatar = random.choice(available) if available else random.choice(avatars)

    players[name] = {
        'score': 0, 'password': password, 'lives': 3,
        'avatar': selected_avatar, 'max_lives': 3
    }
    player_avatars[name] = selected_avatar
    connected_players.add(name)
    power_ups[name] = {"double_points": 0}
    question_streak[name] = 0
    battle_stats[name] = {"correct": 0, "wrong": 0, "hacks_successful": 0, "hacks_failed": 0}

    emit('waiting_status', {'count': len(players)}, broadcast=True)
    emit_players_update()

    if len(players) == 3 and not game_started:
        game_started = True
        emit('start_game', broadcast=True)
        emit('round_update', {'round': current_round, 'max_rounds': max_rounds}, broadcast=True)

def emit_players_update():
    emit('players_update', {
        'players': [
            {'name': name, 'avatar': player_avatars[name], 'score': players[name]['score']}
            for name in players
        ]
    }, broadcast=True)

@socketio.on('get_question')
def on_get_question(data=None):
    name = data.get('name') if data else None
    if not name or name not in players:
        emit('error', {'message': 'Invalid player'})
        return
    question = random.choice(QUESTIONS)
    if random.random() < 0.15:
        question = question.copy()
        question['speed_bonus'] = True
    emit('question', question)

@socketio.on('submit_answer')
def on_submit_answer(data):
    name = data.get('name')
    selected = data.get('selected_option')
    correct = data.get('correct_answer')
    difficulty = data.get('difficulty', 'easy')

    if name not in players:
        emit('error', {'message': 'Invalid submission'})
        return

    player = players[name]
    if selected == correct:
        points = 10 if difficulty == 'easy' else 15
        if power_ups[name]['double_points'] > 0:
            points *= 2
            power_ups[name]['double_points'] -= 1
        player['score'] += points
        question_streak[name] += 1
        battle_stats[name]['correct'] += 1
        emit('answer_result', {'correct': True, 'score': player['score']})
    else:
        player['lives'] -= 1
        question_streak[name] = 0
        battle_stats[name]['wrong'] += 1
        emit('answer_result', {'correct': False, 'lives': player['lives']})

    emit_players_update()
    check_game_over()

def check_game_over():
    global current_round
    current_round += 1
    if current_round > max_rounds or all(p['lives'] <= 0 for p in players.values()):
        emit('game_over', {'final_scores': {
            name: {'score': p['score'], 'avatar': p['avatar']}
            for name, p in players.items()
        }}, broadcast=True)

@socketio.on('lucky_draw')
def on_lucky_draw(data):
    name = data.get('name')
    if name not in players:
        emit('draw_result', {"prize": "Invalid player"})
        return
    prev = player_draw_results.get(name)
    if prev and prev != "Draw Again":
        emit('draw_result', {"prize": "Already Drawn"})
        return
    prize = random.choices(PRIZES, weights=PRIZE_PROBS, k=1)[0]
    player_draw_results[name] = prize
    emit('draw_result', {"prize": prize, "player": name}, broadcast=True)

@socketio.on('power_up')
def on_power_up(data):
    name = data.get('name')
    if name in players:
        power_ups[name]['double_points'] += 1
        emit('power_result', {'player': name, 'power_up': 'double_points'}, broadcast=True)

@socketio.on('initiate_hack')
def on_initiate_hack(data):
    hacker = data.get('hacker')
    target = data.get('target')
    if not hacker or not target or hacker not in players or target not in players:
        emit('error', {'message': 'Invalid hack initiation'})
        return

    correct_password = players[target]['password']
    wrong_passwords = []
    all_passwords = [p['password'] for n, p in players.items() if n != target]
    while len(wrong_passwords) < 2:
        guess = random.choice(all_passwords) if all_passwords else f"pass{random.randint(100,999)}"
        if guess != correct_password and guess not in wrong_passwords:
            wrong_passwords.append(guess)

    guesses = [correct_password] + wrong_passwords
    random.shuffle(guesses)

    emit('start_hack_attempt', {'hacker': hacker, 'target': target, 'guesses': guesses}, room=request.sid)

@socketio.on('hack_attempt')
def on_hack_attempt(data):
    hacker = data.get('hacker')
    guess = data.get('guess')
    target = data.get('target')
    if not hacker or not target or hacker not in players or target not in players:
        emit('error', {'message': 'Invalid hack attempt'})
        return

    correct = players[target]['password']
    success = (guess == correct)
    if success:
        points = min(5, players[target]['score'])
        players[hacker]['score'] += points
        players[target]['score'] -= points
        battle_stats[hacker]['hacks_successful'] += 1
        emit('hack_result', {
            'hacker': hacker,
            'target': target,
            'success': success,
            'points': points if success else 0
        }, room=request.sid)
    if __name__ == '__main__':
        socketio.run(app, host='0.0.0.0', port=5000, use_reloader=False)


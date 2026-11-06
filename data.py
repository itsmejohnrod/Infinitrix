GAMES = {
 'sudoku': {'name':'Sudoku','genre':'Puzzle','description':'Complete an API-generated board.','metric':'seconds'},
 'memory': {'name':'Card Memory','genre':'Memory','description':'Match cards drawn by Deck of Cards API.','metric':'moves'},
 'word': {'name':'Word Detective','genre':'Words','description':'Guess words from dictionary definitions.','metric':'correct'},
 'trivia': {'name':'Trivia Challenge','genre':'Quiz','description':'Answer questions from Open Trivia DB.','metric':'correct'},
 'pokemon': {'name':'Guess the Pokémon','genre':'Guessing','description':'Identify creatures supplied by PokéAPI.','metric':'correct'},
}
DEFAULT_SETTINGS = {'text_size': 'standard', 'reduced_motion': True, 'visual_effects': False,
                    'sound': False, 'volume': 30, 'public_profile': False, 'leaderboard': True}
PASSAGES = [
    'Behind the quiet windows of the city, someone is learning something new. A small idea becomes a plan, a plan becomes a project, and the project becomes a place where friends can play. Every line is another chance to make something thoughtful. Take your time, keep your focus, and let accuracy come before speed. ',
    'The arcade opens when you are ready. There is no rush to beat a record on your first attempt. Read the instructions, find a steady rhythm, and give yourself room to improve. A good game offers a clear challenge and a fair chance to try again. Small steps can carry you farther than you expect. ',
    'Rain settles on the pavement as the evening train arrives. Inside a quiet room, a keyboard marks the rhythm of another project coming together. Simple shapes move across the screen. The best tools leave enough space for people to think, explore, and enjoy what they are making. ',
]
# Original fallback questions, independent of the external provider.
QUESTIONS = [
    ('Which language is used for the Infinitrix backend?', ['Python','CSS','HTML','SQL'], 0),
    ('How many squares are on a standard chessboard?', ['64','32','48','81'], 0),
    ('Which planet is known as the red planet?', ['Mars','Venus','Jupiter','Mercury'], 0),
    ('What does CPU stand for?', ['Central Processing Unit','Computer Power Utility','Control Program User','Central Pixel Unit'], 0),
    ('Which number is prime?', ['17','21','27','33'], 0),
    ('What does HTML describe?', ['The structure of a web page','A password hash','A database table','A network cable'], 0),
    ('Which ocean is the largest?', ['Pacific','Atlantic','Indian','Arctic'], 0),
    ('What is the capital of the Philippines?', ['Manila','Cebu','Davao','Baguio'], 0),
    ('Which tool tracks changes in project files?', ['Git','SQLite','SMTP','Canvas'], 0),
    ('Which symbol begins a Python comment?', ['#','@','$','&'], 0),
]

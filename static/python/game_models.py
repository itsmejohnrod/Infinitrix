"""Pure Python game rules, shared by tests and the browser via PyScript."""

class Random:
    def __init__(self, seed):
        self.state = seed or 1

    def number(self, limit):
        self.state = (1664525 * self.state + 1013904223) % 4294967296
        return self.state % limit

    def shuffle(self, values):
        for i in range(len(values) - 1, 0, -1):
            j = self.number(i + 1)
            values[i], values[j] = values[j], values[i]


class Snake:
    def __init__(self, seed=1, width=24, height=14):
        self.width, self.height = width, height
        self.rng = Random(seed)
        self.body = [(6, 7), (5, 7), (4, 7)]
        self.direction = (1, 0)
        self.next_direction = self.direction
        self.alive, self.score, self.ticks = True, 0, 0
        self.food = self.new_food()

    def new_food(self):
        free = [(x, y) for y in range(self.height) for x in range(self.width)
                if (x, y) not in self.body]
        return free[self.rng.number(len(free))] if free else None

    def turn(self, x, y):
        if (x, y) in [(1, 0), (-1, 0), (0, 1), (0, -1)] and (x, y) != (-self.direction[0], -self.direction[1]):
            self.next_direction = (x, y)

    def step(self):
        if not self.alive:
            return
        self.ticks += 1
        self.direction = self.next_direction
        head = (self.body[0][0] + self.direction[0], self.body[0][1] + self.direction[1])
        eating = head == self.food
        occupied = self.body if eating else self.body[:-1]
        if not (0 <= head[0] < self.width and 0 <= head[1] < self.height) or head in occupied:
            self.alive = False
            return
        self.body.insert(0, head)
        if eating:
            self.score += 10
            self.food = self.new_food()
            if self.food is None:
                self.alive = False
        else:
            self.body.pop()


class Memory:
    def __init__(self, seed=1):
        self.cards = list(range(6)) * 2
        Random(seed).shuffle(self.cards)
        self.matched = set()
        self.first = None
        self.moves = 0

    def choose(self, index):
        if not 0 <= index < 12 or index in self.matched or index == self.first:
            return 'ignored'
        if self.first is None:
            self.first = index
            return 'first'
        previous, self.first = self.first, None
        self.moves += 1
        if self.cards[previous] == self.cards[index]:
            self.matched.update([previous, index])
            return 'match'
        return 'miss'

    @property
    def complete(self):
        return len(self.matched) == 12


LINES = [(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]


def winner(board):
    for a, b, c in LINES:
        if board[a] and board[a] == board[b] == board[c]:
            return board[a]
    return 'draw' if all(board) else None


def computer_move(board):
    """A tactical opponent: win, block, then center, corner, or edge."""
    if winner(board):
        return None
    for mark in ['O', 'X']:
        for i, value in enumerate(board):
            if not value:
                test = board[:]
                test[i] = mark
                if winner(test) == mark:
                    return i
    for i in [4, 0, 8, 2, 6, 1, 3, 5, 7]:
        if not board[i]:
            return i
    return None


def typing_result(text, passage, duration):
    typed = text[:len(passage)]
    correct = sum(1 for a, b in zip(typed, passage) if a == b)
    accuracy = round(100 * correct / len(typed), 1) if typed else 0
    wpm = round((correct / 5) / (duration / 60), 1) if duration > 0 else 0
    return {'score': wpm, 'accuracy': accuracy, 'characters': len(typed)}

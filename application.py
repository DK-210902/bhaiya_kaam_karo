#!flask/bin/python
from dynamodb.connectionManager import ConnectionManager
from dynamodb.gameController import GameController
from models.game import Game
from uuid import uuid4
from flask import Flask, render_template, request, session, flash, redirect, jsonify
import os, time

# Initialize the Flask application
application = Flask(__name__)
application.debug = True  # Enable debugging mode
application.secret_key = str(uuid4())  # Generate a random secret key for session management

# Initialize connection manager and game controller (you might need to adjust these based on your environment)
cm = None
config = None

# Read environment variable for server port or default to 5000
serverPort = int(os.getenv('SERVER_PORT', 5000))

# Read environment variable for whether to read config from EC2 instance metadata
use_instance_metadata = os.getenv('USE_EC2_INSTANCE_METADATA', "")
cm = ConnectionManager(mode='service', config=config, use_instance_metadata=use_instance_metadata)
controller = GameController(cm)

# Route for logging out
@application.route('/logout')
def logout():
    session["username"] = None
    return redirect("/index")

# Route for creating a table
@application.route('/table', methods=["GET", "POST"])
def createTable():
    cm.createGamesTable()

    while not controller.checkIfTableIsActive():
        time.sleep(3)

    return redirect('/index')

# Route for index page and handling user login
@application.route('/')
@application.route('/index', methods=["GET", "POST"])
def index():
    if not session.get("username"):
        form = request.form
        if form:
            formInput = form.get("username")
            if formInput and formInput.strip():
                session["username"] = formInput
            else:
                session["username"] = None
        else:
            session["username"] = None

    if request.method == "POST":
        return redirect('/index')

    inviteGames = controller.getGameInvites(session.get("username"))
    if inviteGames is None:
        flash("Table has not been created yet, please follow this link to create a table.")
        return render_template("table.html", user="")

    inviteGames = [Game(inviteGame) for inviteGame in inviteGames]
    inProgressGames = [Game(inProgressGame) for inProgressGame in controller.getGamesWithStatus(session["username"], "IN_PROGRESS")]
    finishedGames = [Game(finishedGame) for finishedGame in controller.getGamesWithStatus(session["username"], "FINISHED")]

    return render_template("index.html", user=session["username"], invites=inviteGames, inprogress=inProgressGames, finished=finishedGames)

# Route for game creation page
@application.route('/create')
def create():
    if session.get("username") is None:
        flash("Need to login to create a game")
        return redirect("/index")
    return render_template("create.html", user=session["username"])

# Route for handling game creation
@application.route('/play', methods=["POST"])
def play():
    form = request.form
    if form:
        creator = session.get("username")
        gameId = str(uuid4())
        invitee = form.get("invitee").strip()

        if not invitee or creator == invitee:
            flash("Use a valid name (not empty or your own name)")
            return redirect("/create")

        if controller.createNewGame(gameId, creator, invitee):
            return redirect(f"/game={gameId}")

    flash("Something went wrong creating the game.")
    return redirect("/create")

# Route for the game board page
@application.route('/game=<gameId>')
def game(gameId):
    if session.get("username") is None:
        flash("Need to login")
        return redirect("/index")

    item = controller.getGame(gameId)
    if item is None:
        flash("That game does not exist.")
        return redirect("/index")

    boardState = controller.getBoardState(item)
    result = controller.checkForGameResult(boardState, item, session["username"])

    if result:
        if not controller.changeGameToFinishedState(item, result, session["username"]):
            flash("Some error occurred while trying to finish the game.")

    game = Game(item)
    status = game.status
    turn = game.turn

    if game.getResult(session["username"]) is None:
        turn += " (O)" if turn == game.o else " (X)"

    gameData = {'gameId': gameId, 'status': game.status, 'turn': game.turn, 'board': boardState}
    gameJson = jsonify(gameData)

    return render_template("play.html", gameId=gameId, gameJson=gameJson, user=session["username"], status=status, turn=turn,
                           opponent=game.getOpposingPlayer(session["username"]), result=result,
                           TopLeft=boardState[0], TopMiddle=boardState[1], TopRight=boardState[2],
                           MiddleLeft=boardState[3], MiddleMiddle=boardState[4], MiddleRight=boardState[5],
                           BottomLeft=boardState[6], BottomMiddle=boardState[7], BottomRight=boardState[8])

# Route for accepting an invite
@application.route('/accept=<invite>', methods=["POST"])
def accept(invite):
    gameId = request.form.get("response")
    game = controller.getGame(gameId)

    if game is None:
        flash("That game does not exist anymore.")
        return redirect("/index")

    if not controller.acceptGameInvite(game):
        flash("Error accepting the game invite.")
        return redirect("/index")

    return redirect(f"/game={game['GameId']}")

# Route for rejecting an invite
@application.route('/reject=<invite>', methods=["POST"])
def reject(invite):
    gameId = request.form.get("response")
    game = controller.getGame(gameId)

    if game is None:
        flash("That game does not exist anymore.")
        return redirect("/index")

    if not controller.rejectGameInvite(game):
        flash("Error rejecting the invite.")
        return redirect("/index")

    return redirect("/index")

# Route for making a move in the game
@application.route('/select=<gameId>', methods=["POST"])
def selectSquare(gameId):
    value = request.form.get("cell")

    item = controller.getGame(gameId)
    if item is None:
        flash("This is not a valid game.")
        return redirect("/index")

    if not controller.updateBoardAndTurn(item, value, session["username"]):
        flash("Invalid move: It's either not your turn, the square is already selected, or the game is not 'In-Progress'.", "updateError")
        return redirect(f"/game={gameId}")

    return redirect(f"/game={gameId}")

# Start the Flask application
if __name__ == "__main__":
    if cm:
        application.run(debug=True, port=serverPort, host='0.0.0.0')

import os

from cs50 import SQL
from flask import Flask, flash, jsonify, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime
import re

from helpers import apology, login_required, lookup, usd, User

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

"""
# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")
"""

# cache user quote requests
quoteList = []


@app.route("/")
@login_required
def index():

    # get user folio from database and populate
    db_folio = db.execute("SELECT folio FROM users WHERE id = :user_id", user_id=session["user_id"])

    # check for new user or empty portfolio
    if not db_folio[0]["folio"]:
        return render_template("index.html", cash=user.dollars(), assets=user.dollars())

    # format database info into 2D array, sum assets, and send to template
    else:
        folio = list(map(str.strip, db_folio[0]["folio"].split(",")))
        i = 0
        holdings = []
        assets = user.balance()
        while i < len(folio):
            quote = lookup(folio[i])
            assets += quote["price"] * int(folio[i + 1])
            holdings.append([
                quote["symbol"],
                quote["name"],
                folio[i + 1],
                usd(quote["price"]),
                usd(int(folio[i + 1]) * quote["price"])
            ])
            i += 2
        assets = usd(assets)

        return render_template("index.html", cash=user.dollars(), folio=holdings, assets=assets)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():

    # check user balance
    if request.method == "GET":
        if user.balance() < 0.01:
            return apology("You have no available funds", 403)
        else:
            return render_template("buy.html", cash=user.dollars(), quoteList=quoteList)

    if request.method == "POST":
        symbol = request.form.get("symbol").upper()
        invalid = re.findall("[^A-Z]", symbol)
        if invalid:
            return apology("Invalid ticker symbol", 400)
        try:
            buying = int(request.form.get("shares"))
        except ValueError:
            return apology("Invalid shares", 400)
        # check user input
        if not symbol or not buying or buying <= 0:
            return apology("Invalid entry", 400)
        else:
            quote = lookup(symbol)
            cost = buying * quote["price"]
            # check user balance vs cost
            if cost > user.balance():
                return apology("Cannot afford " + usd(cost), 400)
            else:
                # pay for stocks
                db.execute("UPDATE users SET cash = :nu_bal WHERE id = :user_id",
                           nu_bal=user.balance() - cost, user_id=session["user_id"])
                user.update(cost)
                # add stocks to user db
                db_obj = db.execute("SELECT folio FROM users WHERE id = :user_id",
                                    user_id=session["user_id"])
                add = False
                shares = 0
                # check for new user or empty portfolio
                if not db_obj[0]["folio"]:
                    folio = [quote["symbol"], str(buying)]
                    add = True
                else:
                    folio = list(map(str.strip, db_obj[0]["folio"].split(",")))
                    for i in range(len(folio)):
                        if folio[i] == quote["symbol"]:
                            shares = int(folio[i + 1])
                            folio[i + 1] = str(shares + buying)
                            add = True
                    if add == False:
                        folio.extend([quote["symbol"], str(buying)])
                folio = ",".join(folio)
                db.execute("UPDATE users SET folio = :folio WHERE id = :user_id",
                           folio=folio, user_id=session["user_id"])

                # add history entry
                db.execute(
                    "INSERT INTO history (id, trade, shares, symbol, price, datetime) VALUES(:user_id, :trade, :shares, :symbol, :price, :datetime)",
                    user_id=session["user_id"],
                    trade="Buy",
                    shares=buying,
                    symbol=symbol,
                    price=quote["price"],
                    datetime=datetime.now()
                )

                return redirect("/")


@app.route("/check", methods=["GET"])
def check():

    # Return true if username available, else false, in JSON format
    match = db.execute("SELECT * from users WHERE username = :username",
                       username=request.args["username"])
    if match:
        return jsonify(False)
    else:
        return jsonify(True)


@app.route("/history")
@login_required
def history():

    # retrieve history object from db
    db_history = db.execute(
        "SELECT trade, shares, symbol, price, datetime FROM history WHERE id = :user_id",
        user_id=session["user_id"]
    )
    history = []
    for row in reversed(db_history):
        history.append(row.values())

    return render_template("history.html", cash=user.dollars(), history=history)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        db_obj = db.execute("SELECT * FROM users WHERE username = :username",
                            username=request.form.get("username"))

        # Ensure username exists and password is correct
        if len(db_obj) != 1 or not check_password_hash(db_obj[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = db_obj[0]["id"]

        # Create user object
        global user
        user = User(db_obj)

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id and clear cached lookup()
    session.clear()
    global user
    user = {}
    global quoteList
    quoteList = []

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():

    # display quote cache
    if request.method == "GET":
        return render_template("quote.html", cash=user.dollars(), quoteList=quoteList)

    # handle new quote request
    if request.method == "POST":
        symbol = request.form.get("symbol").upper()
        invalid = re.findall("[^A-Z]", symbol)
        if invalid or not symbol:
            return apology("Invalid ticker symbol", 400)
        else:
            quoteList.insert(0, lookup(symbol))
            return render_template("quote.html", cash=user.dollars(), quoteList=quoteList)


@app.route("/register", methods=["GET", "POST"])
def register():

    # display form
    if request.method == "GET":
        return render_template("register.html")

    # get form input
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")
        if not username or not password or not confirmation or password != confirmation:
            return apology("Please enter a username and password", 400)

        # check if user already exists
        db_obj = db.execute("SELECT * FROM users WHERE username = :username", username=username)
        if db_obj:
            return apology("That username is already taken", 400)

        # hash password and create user in db
        hashed = generate_password_hash(password, method="pbkdf2:sha256")
        db.execute("INSERT INTO users (username, hash) VALUES(:username, :hashed)", username=username, hashed=hashed)

        # log in new user and place them at index
        db_obj = db.execute("SELECT * FROM users WHERE username = :username", username=username)
        session["user_id"] = db_obj[0]["id"]
        return redirect("/logout")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():

    # get user folio from database
    db_folio = db.execute("SELECT folio FROM users WHERE id = :user_id",
                          user_id=session["user_id"])

    if request.method == "GET":

        # check for new user or empty portfolio
        if not db_folio[0]["folio"]:
            return apology("You have no holdings", 403)

        # format database info into 2D array, sum assets, and send to template
        else:
            folio = list(map(str.strip, db_folio[0]["folio"].split(",")))
            i = 0
            holdings = []
            assets = user.balance()
            while i < len(folio):
                quote = lookup(folio[i])
                assets += quote["price"] * int(folio[i + 1])
                holdings.append([
                    quote["symbol"],
                    quote["name"],
                    folio[i + 1],
                    usd(quote["price"]),
                    usd(int(folio[i + 1]) * quote["price"])
                ])
                i += 2
            assets = usd(assets)

            return render_template("sell.html", cash=user.dollars(), folio=holdings, assets=assets)

    if request.method == "POST":
        symbol = request.form.get("symbol").upper()
        try:
            selling = int(request.form.get("shares"))
        except ValueError:
            return apology("Invalid number of shares", 400)

        # check user input
        if not symbol or not selling or selling <= 0:
            return apology("Invalid entry", 400)

        # format db_folio into list
        folio = list(map(str.strip, db_folio[0]["folio"].split(",")))

        # check folio for sale request
        for i in range(len(folio)):
            if folio[i] == symbol:
                if int(folio[i + 1]) < selling:
                    return apology("You dont own that many shares", 400)
                else:
                    quote = lookup(symbol)
                    cost = quote["price"] * selling
                    if int(folio[i + 1]) == selling:
                        folio[i:i + 2] = []
                    else:
                        folio[i + 1] = str(int(folio[i + 1]) - selling)
                    folio = ",".join(folio)
                    db.execute("UPDATE users SET cash = :nu_bal WHERE id = :user_id",
                               nu_bal=user.balance() + cost, user_id=session["user_id"])
                    user.update(-cost)
                    db.execute("UPDATE users SET folio = :folio WHERE id = :user_id",
                               folio=folio, user_id=session["user_id"])
                    break

        # add history entry
        db.execute(
            "INSERT INTO history (id, trade, shares, symbol, price, datetime) VALUES(:user_id, :trade, :shares, :symbol, :price, :datetime)",
            user_id=session["user_id"],
            trade="Sell",
            shares=selling,
            symbol=symbol,
            price=quote["price"],
            datetime=datetime.now()
        )

        return redirect("/")


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)


"""
ROADMAP:
1. Implement register() where a new user is created:
    create template for registration form including username, 2xpassword, and submit
    check that a username and password was input and that both passwords match
    submit via POST to /register
    hash user password using werkzeug.security
    INSERT new user into users and store hash

    tech-debt: improve html of register.html with form entry code verification week7
    tech-debt: add bootstrap css to ameliorate the table

2. Implement quote() where a user can find the price of a stock
    create template for search using form stock ticker input whose name="symbol"
        use if GET/POST format to allow new searches and displaying lookup() results

    tech-debt: add bootstrap css to ameliorate the table

3. Implement buy() where a user can buy a stock
    apologize if no funds
    ask user ticker and number of shares
        verify user input, user funds
    purchase, add to history, and redirect to index

    tech-debt: add bootstrap css to ameliorate the table
    tech-debt: after buy, tell index how landed there

4. Implement index() return current state of user portfolio:
    also user homepage, add user funds
    table with: stocks owned, shares, current price, total holding value
    display total value of funds and all holdings

    tech-debt: show how landed at index

5. Implement sell() where a user can sell a stock
    if there is a portfolio, use template for index

    tech-debt: after sell, tell index how landed there

6. Implement history() return history of all buy() and sell()
    create a history table in db
        fields are: id(integer), type(bool) True is buy, symbol(char(5)),
        price(real), shares(integer), date+time(datetime)
    update buy and sell methods to add history entry
    when nav to history, retrieve from db all user transactions with newest at top
        history array should add discoveries to beginning to keep newest at top

    tech-debt:

7. Implement check() to see if a username is available for register()

    tech-debt:
"""
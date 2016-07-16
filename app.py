#!/usr/bin/env python3

# The MIT License (MIT)

# Copyright (c) 2016 RascalTwo @ therealrascaltwo@gmail.com

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Reddit bot that posts Google Alert RSS feed items to subreddits."""

import xml.etree.ElementTree as ET
from html.parser import HTMLParser
import threading
import requests
import sqlite3
import wsgiref.util
import wsgiref.simple_server
import praw
import json
import time


class MLStripper(HTMLParser):
    """Parser to remove HTML tags and entities from string."""

    def __init__(self):
        """Initalize parser."""
        super().__init__(convert_charrefs=False)
        self.reset()
        self.fed = []

    def handle_data(self, data):
        """Hangle data given to the parser."""
        self.fed.append(data)

    def get_data(self):
        """Return result of parser."""
        return ''.join(self.fed)

    @staticmethod
    def strip_tags(html):
        """Strip HTML tags and entities from string."""
        stripper = MLStripper()
        stripper.feed(html)
        return stripper.get_data()


class GoogleAlertRSSPoster(object):
    """Reddit bot that posts Google Alert RSS feed items to subreddits."""

    def __init__(self):
        """Create databases, load config file, and login to reddit."""
        self.running = False

        with open("config.json", "r") as config_file:
            self.config = json.loads(config_file.read())

        self.db = sqlite3.connect("database.db")
        cur = self.db.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS posts(
                url         TEXT  NOT NULL  PRIMARY KEY,
                title       TEXT  NOT NULL,
                utc         INT   NOT NULL,
                permalinks  TEXT  NOT NULL,
                subreddits  TEXT  NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS history(
                url         INT   NOT NULL,
                title       TEXT  NOT NULL,
                utc         TEXT  NOT NULL  PRIMARY KEY,
                permalink   TEXT  NOT NULL,
                subreddit   TEXT  NOT NULL
            )
        """)
        cur.execute("""
            CREATE TRIGGER IF NOT EXISTS limit_1k AFTER INSERT ON posts
              BEGIN
                DELETE FROM posts WHERE utc <= (SELECT utc FROM posts ORDER BY utc DESC LIMIT 1000, 1);
              END;
        """)
        cur.execute("""
            CREATE TRIGGER IF NOT EXISTS limit_1k AFTER INSERT ON history
              BEGIN
                DELETE FROM history WHERE utc <= (SELECT utc FROM history ORDER BY utc DESC LIMIT 1000, 1);
              END;
        """)
        cur.close()
        self.db.commit()
        self.db.close()

        self.reddit = praw.Reddit(self.config["user_agent"])
        self.reddit.login(self.config["username"],
                          self.config["password"],
                          disable_warning="True")

    def _headers(self):
        return {
            "User-Agent": self.config["user_agent"]
        }

    def _query(self, statement, arguments=(), amount=None):
        """Perform query on database, returning amount of rows."""
        cur = self.db.cursor()
        cur.execute(statement, arguments)
        results = cur.fetchall()
        cur.close()
        if results is None or results == []:
            return None
        if amount is None:
            return results
        if amount > 1:
            returning = []
            for i in range(amount):
                try:
                    returning.append(results[i])
                except:
                    break
            return returning

    def _execute(self, statement, arguments=()):
        """Execute a statement on database, returning nothing."""
        cur = self.db.cursor()
        cur.execute(statement, arguments)
        cur.close()
        self.db.commit()

    def _list_as(self, list_in, return_type):
        """Return a '|'-split list as a list or str."""
        if return_type == "str":
            if isinstance(list_in, str):
                return list_in
            return "|".join(list_in)
        elif return_type == "list":
            if isinstance(list_in, list):
                return list_in
            if len(list_in) == 1:
                return list_in[0]
            return list_in.split("|")

    def items_as(self, items, return_type):
        """Return items as either a 'dict' or 'json'."""
        return_single = False
        results = []
        if not isinstance(items, list):
            return_single = True
            items = [items]
        for item in items:
            if return_type == "dict":
                if isinstance(item, dict):
                    results.append(item)
                    continue
                results.append({
                    "url": item[0],
                    "title": item[1],
                    "utc": item[2],
                    "permalinks": self._list_as(item[3], "list"),
                    "subreddits": self._list_as(item[4], "list"),
                })
            elif return_type == "tuple":
                if isinstance(item, tuple):
                    results.append(item)
                    continue
                results.append((
                    item["url"],
                    item["title"],
                    item["utc"],
                    self._list_as(item["permalinks"], "str"),
                    self._list_as(item["subreddits"], "str")
                ))
        if return_single:
            return results[0]
        return results

    def _from_database(self, url):
        """Get entry from database with matching url."""
        result = self._query("SELECT * FROM posts "
                             "WHERE url = ?", (url,))
        if result is None:
            return None
        return self.items_as(result[0], "dict")

    def _get_items(self):
        """Get items from feeds."""
        feeds = []
        for feed in self.config["feeds"]:
            raw = requests.get(feed["url"], headers=self._headers()).text.replace('xmlns="http://www.w3.org/2005/Atom"', "")
            feeds.append((ET.fromstring(raw), feed["subreddits"]))
        items = []
        for feed in feeds:
            for item in feed[0]:
                if item.tag != "entry":
                    continue
                entry = {
                    "title": MLStripper.strip_tags(item.find("title").text),
                    "url": item.find("link").attrib["href"].split("&url=")[1],
                    "subreddits": feed[1]
                }
                if "&" in entry["url"]:
                    entry["url"] = entry["url"].split("&")[0]
                items.append(entry)
        return items

    def _get_db_items(self, items):
        """Return rows for items."""
        statement = ("SELECT * FROM posts WHERE url IN ({})"
                     .format(", ".join(["?"] * len(items))))
        urls = [item["url"] for item in items]
        results = self._query(statement, urls)
        if results is None:
            return []
        return self.items_as(results, "dict")

    def _insert_db_item(self, item):
        """Insert item into database."""
        self._execute("INSERT OR REPLACE INTO posts "
                      "VALUES (?, ?, ?, ?, ?)",
                      self.items_as(item, "tuple"))

    def _insert_history(self, item):
        """Insert history of item being inserted into database."""
        self._execute("INSERT INTO history "
                      "VALUES (?, ?, ?, ?, ?)",
                      (item["url"],
                       item["title"],
                       int(time.time()),
                       item["permalinks"][-1],
                       item["subreddits"][-1]))

    def run(self):
        """Start the bot main loop."""
        self.db = sqlite3.connect("database.db", check_same_thread=False)
        while True:
            items = self._get_items()
            for item in items:
                entry = self._from_database(item["url"])
                for sub in item["subreddits"]:
                    if entry is not None:
                        if sub in entry["subreddits"]:
                            continue
                        item["utc"] = entry["utc"]
                        item["permalinks"] = entry["permalinks"]
                    else:
                        item["permalinks"] = []
                    subreddit = self.reddit.get_subreddit(sub)
                    try:
                        post = subreddit.submit(item["title"],
                                                url=item["url"],
                                                resubmit=self.config["resubmit"])
                    except praw.errors.AlreadySubmitted:
                        post = list(subreddit.search(item["url"]))[0]
                    except praw.errors.RateLimitExceeded:
                        item["subreddits"].remove(sub)
                        self._insert_db_item(item)
                        entry = self._from_database(item["url"])
                        continue
                    item["utc"] = int(time.time())
                    if isinstance(item["permalinks"], str):
                        item["permalinks"] = [
                            item["permalinks"],
                            post.permalink
                        ]
                    else:
                        item["permalinks"].append(post.permalink)
                    self._insert_db_item(item)
                    print("Title:      {item[title]}\n"
                          "URL:        {item[url]}\n"
                          "Subreddit:  {0}\n"
                          "Permalink:  {1}\n"
                          .format(sub,
                                  item["permalinks"][-1],
                                  item=item))
                    self._insert_history(item)
            print("Waiting...\n")
            time.sleep(self.config["check_rate"])

def strip_args(path):
    args = {}
    for arg in [(arg.split("=")[0], arg.split("=")[1]) for arg in path.split("&")[1:]]:
        args[arg[0]] = arg[1]
    return args

def table_data(path, start_response, table):
    start_response('200 OK', [('Content-type', 'application/json')])
    args = strip_args(path)
    fetch_range = args["range"].split("-")
    results = bot._query("SELECT * FROM " + table + " "
                         "ORDER BY utc DESC LIMIT ?, ?",
                         (fetch_range[0], fetch_range[1]))

    if results is None:
        return [json.dumps({"stop": True}).encode("utf-8")]
    stop = bot._query("SELECT * FROM " + table + " "
                      "ORDER BY utc DESC LIMIT ?, 1",
                      (fetch_range[1],))
    return [json.dumps({
        "stop": True if stop is None else False,
        "data": bot.items_as(results, "dict")
    }).encode("utf-8")]

def simple_app(environ, start_response):
    path = environ["PATH_INFO"]
    if path == "/":
        start_response('200 OK', [('Content-type', 'text/html')])

        with open("index.html", "r") as index:
            html = index.read()

        history = bot._query("SELECT * FROM history ORDER BY utc DESC LIMIT 0, 10 ")
        html = html.replace("-={HISTORY}=-", json.dumps(bot.items_as(history, "dict")))

        return [html.encode("utf-8")]
    elif "/api/history" in path:
        return table_data(path, start_response, "history")
    elif "/api/posts" in path:
        return table_data(path, start_response, "posts")
    else:
        start_response('404 NOT FOUND', [])
        return ["".encode("utf-8")]


if __name__ == "__main__":
    bot = GoogleAlertRSSPoster()
    thread = threading.Thread(target=bot.run, name="Bot")
    thread.daemon = True
    thread.start()

    httpd = wsgiref.simple_server.make_server('', 8000, simple_app)
    print("Serving on port 8000...")
    httpd.serve_forever()

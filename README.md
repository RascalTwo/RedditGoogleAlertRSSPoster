# Google Alert RSS Feed Poster

Submit link posts from Google Alert RSS feeds to target subreddits.

*****

# Dependancies

*****

- PRAW
- Requests

Makes posts using the PRAW library while tracking posts made and history via a sqlite3 database.

*****

# Configuration

*****

All configurations are made via the `config.json` file.

```JSON
{
    "user_agent": "",
    "username": "",
    "password": "",
    "check_rate": 60,
    "resubmit": false,
    "feeds": [
        {
            "url": "https://www.google.com/alerts/feeds/09844433320831210961/3504146379976622958",
            "subreddits": [
                "Test"
            ]
        }
    ]
}
```

- `user_agent`
    - What Google and Reddit sees the bot as, the more unique this is the better.
- `username`
    - Username of the reddit account making the posts.
- `password`
    - Password of the Reddit account making the posts.
- `check_rate`
    - How often - in seconds - to check the RSS feeds and make posts.
- `resubmit`
    - If the bot should repost a link even though it's been posted before according to Reddit.
    - This only applies to the bots first post, as it won't resubmit if it has already posted before.
- `feeds`
    - List of Feed objects.

A feed consists of two properties:

- `url`
    - The URL to the Google Alert RSS feed.
- `subreddits`
    - List of subreddits to post the feed items to.

*****

# Technical Breakdown

*****

## Databases

*****

The bot has two databases, `posted` and `history`.

### Posts

URL | Title | UTC | Permalinks | Subreddits
--- |  ---  | --- |     ---    |    ---
http://example.com/ | Example thing | 1451606400 | http://reddit.com/Test/1234567/example-com/ | Test

Permalinks and Subreddits are added two if there are more then two subreddits the item is posted to.

Only 1000 entries are kept in the table.

### History

URL | Title | UTC | Permalink | Subreddit
--- |  ---  | --- |     ---   |    ---

This is an log of the posting the bot has done.

Only 1000 entries are kept in the table.

*****

## Walkthough

*****

- Tables and triggers are created if they're don't already exist.
- Reddit is logged into.
- While the bot is running:
    - List of items are gotten from all feeds
    - For every item in the list of items:
        - An attempt is made to get the `posted` database entry with the same URL of the current item.
        - For every target subreddit the item needs to be posted to:
            - If there is an entry in the database for the current item and the `subreddits` column contains the current subreddit, the post is not made.
            - An attempt to make the post is made
            - The database is updated.
    - The bot waits `check_rate` seconds, and does the above items again.

# Web-GUI

It's a simple GUI that shows the contents of the `posts` or `history` tables in list form.

The `Toggle` button switches between Posts and History.

The `Refresh` button does as it says, and refreshes the current content.

The `Next` and `Previous` buttons - when available - show the next or previous ten entries in the current database.

## Technical details

The backend API is as such:

`/api/table_name&range=0-10`

where `table_name` is the name of the current table - `posts` or `history`, the first number in range is the number of the element to start from, and the second number is how many elements to fetch.
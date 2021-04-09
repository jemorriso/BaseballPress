from datetime import date
import re

from bs4 import BeautifulSoup
import requests


def extract_int(str):
    m = re.search(r"\d+", str)
    if m is not None:
        return int(m.group())
    else:
        return None


class DateGames:
    def __init__(self, date_str="", parse=True):
        self._url = "https://www.baseballpress.com/lineups"

        self.date = date_str if date_str else date.today().isoformat()
        self.games = []
        self._records = []

        raw = self._scrape()
        self.raw = raw

        if parse:
            self.games = self.parse()
        # self.records = self.scrape()

    def _gen_soup(self, raw):
        return BeautifulSoup(raw, features="html.parser")

    def _validate_games(self, games):
        return [g for g in games if g.attrs.get("data-league") is not None]

    def _find_games(self, soup):
        containers = soup.select(".ccm-page > .container")
        for c in containers:
            games_container = c.select_one(".lineups")
            if games_container:
                games = games_container.select(".lineup-col")
                games = self._validate_games(games)
                return games
        return []

    def _scrape(self):
        print(f"Scraping data for {self.date}...")
        res = requests.get(f"{self._url}/{self.date}")
        soup = self._gen_soup(res.text)
        raw = soup.prettify()
        return raw

    def _scrape_games(self, game_containers):
        games = []
        for gc in game_containers:
            game = Game(gc)
            games.append(game)
        return games

    def parse(self):
        soup = self._gen_soup(self.raw)
        game_containers = self._find_games(soup)
        if not game_containers:
            raise ValueError("No games discovered on this date.")

        games = self._scrape_games(game_containers)
        if not self.games:
            self.games = games

        print("All done!")
        return games

    def records(self):
        if self._records:
            records = self._records
        else:
            records = []
            for g in self.games:
                records.extend(g.records())

            for r in records:
                r["Date"] = self.date

            self._records = records

        return records


class Game:
    def __init__(self, soup):
        self.raw = soup.prettify()

        (
            self.home,
            self.away,
            self.time,
            self.farenheit,
            self.precipitation,
        ) = self.parse(soup)

    def _parse_time(self, container):
        time_str = container.select("div")[-1].get_text()
        return time_str.strip()

    def _parse_farenheit(self, div):
        # Sets to None if not available.
        return extract_int(div.get_text())

    def _parse_precipitation(self, div):
        # Sets to None if not available.
        return extract_int(div.get_text())

    def _parse_teams(self, team_dict):
        teams = []
        for t in team_dict.values():
            team = Team(t)
            teams.append(team)
        return teams

    def _parse_game(self, game_dict):
        time = self._parse_time(game_dict["time"])
        farenheit = self._parse_farenheit(game_dict["farenheit"])
        precipitation = self._parse_precipitation(game_dict["precipitation"])
        return time, farenheit, precipitation

    def _parse_header(self, html):
        rows = html.select(".row")
        teams_and_gametime = rows[0]
        cols = teams_and_gametime.select(".col")

        gametime = cols[1]
        home_ids = cols[0]
        away_ids = cols[-1]

        # Will always have 'TBD' if not available yet.
        home_pitcher, away_pitcher = rows[1].select(".player")

        return {
            "game": {"time": gametime},
            "teams": {
                "home": {"ids": home_ids, "pitcher": home_pitcher},
                "away": {"ids": away_ids, "pitcher": away_pitcher},
            },
        }

    def _parse_body(self, html):
        # If rotation not available, will have 'No Lineup Released'.
        home_rotation, away_rotation = html.select(".col")
        return {
            "teams": {
                "home": {"rotation": home_rotation},
                "away": {"rotation": away_rotation},
            },
        }

    def _parse_footer(self, html):
        col = html.select_one(".col-8")
        divs = col.select("div")

        # If weather not available, the div elements are present with no values filled
        # in.
        return {"game": {"farenheit": divs[0], "precipitation": divs[1]}}

    def _parse_rotations(self, rotations_containers):
        for r, t in list(zip(rotations_containers, self.teams())):
            t._parse_rotation(r)
        pass

    def _extract_object_html(self, soup):
        game_header = soup.select_one(".lineup-card-header")
        game_body = soup.select_one(".lineup-card-body")
        game_footer = soup.select_one(".lineup-card-footer")

        object_html = {"game": {}, "teams": {"home": {}, "away": {}}}
        header_html = self._parse_header(game_header)
        body_html = self._parse_body(game_body)
        footer_html = self._parse_footer(game_footer)

        for h in [header_html, body_html, footer_html]:
            if "game" in h:
                object_html["game"].update(h["game"])
            if "teams" in h:
                for t in ["home", "away"]:
                    object_html["teams"][t].update(h["teams"][t])

        return object_html

    def teams(self):
        return [self.home, self.away]

    def parse(self, soup):
        object_html = self._extract_object_html(soup)

        home, away = self._parse_teams(object_html["teams"])

        print(f"Scraping game data for {home.name} vs. {away.name}...")
        time, farenheit, precipitation = self._parse_game(object_html["game"])

        return home, away, time, farenheit, precipitation

    def _add_record(self, team_record, opp, is_home):

        return {
            **{
                "Time": self.time,
                "Farenheit": self.farenheit,
                "Precipitation": self.precipitation,
                "Is Home": is_home,
                "Opponent Name": opp.name,
                "Opponent Abbreviation": opp.abbreviation,
            },
            **team_record,
        }

    def records(self):
        def add_team_records(team, opp):
            rs = []
            for r in team.records():
                rs.append(self._add_record(r, opp, team == self.home))
            return rs

        rs = []
        rs.extend(add_team_records(self.home, self.away))
        rs.extend(add_team_records(self.away, self.home))

        return rs


class Team:
    def __init__(self, team_dict):
        self.name, self.abbreviation, self.pitcher, self.rotation = self.parse(
            team_dict
        )

    def _is_valid_rotation(self, container):
        return "no lineup released" not in container.get_text().lower()

    def _parse_abbreviation(self, container):
        team_link = container.select_one("a").attrs.get("href")
        return team_link.split("/")[-1].upper()

    def _parse_name(self, container):
        return container.select_one("div").get_text().strip()

    def _parse_pitcher(self, html):
        return Pitcher(html)

    def _parse_rotation(self, container):
        rotation = []
        if self._is_valid_rotation(container):
            player_containers = container.select(".player")
            for p in player_containers:
                batter = Batter(p)
                rotation.append(batter)
            rotation.append(batter)
        return rotation

    def _add_record(self, player_record):
        return {
            **{"Team Name": self.name, "Team Abbreviation": self.abbreviation},
            **player_record,
        }

    def records(self):
        rs = []
        rs.append(self.pitcher.record())
        for b in self.rotation:
            rs.append(b.record())
        rs = [self._add_record(r) for r in rs]
        return rs

    def parse(self, team_dict):
        name = self._parse_name(team_dict["ids"])
        abbreviation = self._parse_abbreviation(team_dict["ids"])
        pitcher = self._parse_pitcher(team_dict["pitcher"])
        rotation = self._parse_rotation(team_dict["rotation"])

        return name, abbreviation, pitcher, rotation


class Player:
    def __init__(self):
        self.name = self.handedness = self.mlb_id = None

    def _clean_player(self, p_str):
        pl = p_str.splitlines()
        pl = [p for p in pl if p and not p.isspace()]
        return [p.strip() for p in pl]

    def _parse_name(self, a):
        # Sometimes the player might have a desktop name and a mobile name.
        span = a.select_one(".desktop-name")
        if span:
            return span.get_text().strip()
        else:
            return a.get_text().strip()

    def _parse_mlb_id(self, a):
        return a.attrs.get("data-mlb")

    def parse(self, container):
        player_a = container.select_one("a")
        name = self._parse_name(player_a)
        mlb_id = int(self._parse_mlb_id(player_a))
        return name, mlb_id

    def record(self):
        return {"ID": self.mlb_id, "Name": self.name, "Handedness": self.handedness}


class Batter(Player):
    def __init__(self, soup):
        super().__init__()

        self.order, self.name, self.handedness, self.mlb_id, self.position = self.parse(
            soup
        )

    def _parse_order(self, i_str):
        return extract_int(i_str)

    def _parse_handedness(self, hand_str):
        return hand_str.replace("(", "").replace(")", "")

    def _parse_position(self, pos_str):
        return pos_str

    def parse(self, soup):
        p = self._clean_player(soup.get_text())
        hand_str, pos_str = p[-1].split(" ")

        name, mlb_id = super().parse(soup)
        order = self._parse_order(p[0])
        handedness = self._parse_handedness(hand_str)
        position = self._parse_position(pos_str)
        return order, name, handedness, mlb_id, position

    def record(self):
        r = super().record()
        return {**r, **{"Position": self.position, "Order": self.order}}


class Pitcher(Player):
    def __init__(self, soup):
        super().__init__()
        if not self._is_valid_pitcher(soup):
            self.position = None
            return
        self.name, self.handedness, self.mlb_id, self.position = self.parse(soup)

    def _is_valid_pitcher(self, html):
        return "TBD" not in html.get_text()

    def _parse_handedness(self, hand_str):
        return hand_str.replace("(", "").replace(")", "")

    def _parse_position(self):
        return "P"

    def parse(self, soup):
        p = self._clean_player(soup.get_text())
        name, mlb_id = super().parse(soup)
        handedness = self._parse_handedness(p[-1])
        position = self._parse_position()

        return name, handedness, mlb_id, position

    def record(self):
        r = super().record()
        return {**r, **{"Position": self.position}}


if __name__ == "__main__":
    # All information
    d = DateGames("2021-03-17")

    # No games at all
    # try:
    #     DateGames("2020-12-29")
    # except ValueError as e:
    #     print(e)

    # No game information
    # d = DateGames("2021-03-26")

    r = d.records()
    pass

import copy
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from typing import Callable

from constants import OUTPUT_DEBUG, OUTPUT_ERROR
from game_node import GameNode


class KataGoEngine:
    """Starts and communicates with the KataGO analysis engine"""

    # TODO: we don't support suicide in game.py, so no  "tt": "tromp-taylor", "nz": "new-zealand"
    RULESETS = {"jp": "japanese", "cn": "chinese", "ko": "korean", "aga":"aga"}
    RULESETS.update({v: v for v in RULESETS.values()})

    def __init__(self, katrain, config):
        self.command = os.path.join(config["command"])
        self.katrain = katrain
        if "win" not in sys.platform:
            self.command = shlex.split(self.command)
        self.queries = {}
        self.config = config
        self.visits = [config["visits"], config["visits_fast"]]
        self.fast = True
        self.query_counter = 0
        self.katago_process = None

        try:
            self.katago_process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            self.analysis_thread = threading.Thread(target=self._analysis_read_thread, daemon=True).start()
        except FileNotFoundError:
            self.katrain.log(
                f"Starting kata with command '{self.command}' failed. If you are on Mac or Linux, please edit configuration file (config.json) to point to the correct KataGo executable.",
                OUTPUT_ERROR,
            )

    def _analysis_read_thread(self):
        while True:
            line = self.katago_process.stdout.readline()
            analysis = json.loads(line)
            if "error" in analysis:
                self.katrain.log(f"ERROR IN KATA ANALYSIS: {analysis['error']}")
            else:
                callback, start_time = self.queries[analysis["id"]]
                time_taken = time.time() - start_time
                self.katrain.log(f"[{time_taken:.1f}][{analysis['id']}] KataGo Analysis Received: {line}...") # [:80]
                callback(analysis)
                self.katrain.redraw()

    def request_analysis(
        self, analysis_node: GameNode, callback: Callable, faster=False, min_visits=0, priority=0, ownership=None
    ):
        query_id = f"QUERY:{str(self.query_counter)}"
        self.query_counter += 1
        visits = 100  # TODO  /         fast = self.ai_fast.active
        if faster:
            visits /= 5
        moves = [m for node in analysis_node.nodes_from_root for m in node.move_with_placements]

        if ownership is None:
            ownership = self.config["enable_ownership"]


        query = {
            "id": query_id,
            "rules": self.RULESETS.get( str(analysis_node.ruleset).lower(), "japanese"),
            "priority": priority,
            "analyzeTurns": [len(moves)],
            "maxVisits": max(min_visits, visits),
            "komi": analysis_node.komi,
            "boardXSize": analysis_node.board_size,
            "boardYSize": analysis_node.board_size,
            "includeOwnership": ownership,
            "moves": [[m.player, m.gtp()] for m in moves],
        }
        self.queries[query_id] = (callback, time.time())
        if self.katago_process:
            self.katrain.log(f"Sending query {query_id}: {str(query)}", OUTPUT_DEBUG) # [:80]
            self.katago_process.stdin.write((json.dumps(query) + "\n").encode())
            self.katago_process.stdin.flush()

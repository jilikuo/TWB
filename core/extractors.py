"""
File used for data extraction
"""

import json
import re
import logging


class Extractor:
    """
    Defines various non-compiled regexes for data retrieval
    TODO: use compiled various for CPU efficiency
    """
    logger = logging.getLogger('Extractor')

    @staticmethod
    def _extract_text_content(res):
        """
        Helper to safely extract text from a response object.
        """
        if res is None:
            Extractor.logger.warning("Extraction failed. Response was None.", stack_info=True)
            return None
        
        if isinstance(res, str):
            return res
        
        if hasattr(res, 'text') and res.text:
            return res.text

        Extractor.logger.warning(
            f"Extraction failed: Object of type '{type(res).__name__}' has no valid '.text' attribute. Object: {res}",
            stack_info=True
        )
        return None
            
    @staticmethod
    def village_data(res):
        """
        Detects village data on a page
        """
        text = Extractor._extract_text_content(res)
        if not text:
            return None

        grabber = re.search(r'var village = (.+);', text)
        if grabber:
            data = grabber.group(1)
            return json.loads(data, strict=False)

    @staticmethod
    def game_state(res):
        """
        Detects the game state that is available on most pages
        """
        text = Extractor._extract_text_content(res)
        if not text:
            return None
        
        grabber = re.search(r'TribalWars\.updateGameData\((.+?)\);', text)
        if grabber:
            data = grabber.group(1)
            return json.loads(data, strict=False)

    @staticmethod
    def building_data(res):
        """
        Fetches building data from the main building
        """
        text = Extractor._extract_text_content(res)
        if not text:
            return None
        
        dre = re.search(r'(?s)BuildingMain.buildings = (\{.+?\});', text)
        if dre:
            return json.loads(dre.group(1), strict=False)

        return None

    @staticmethod
    def get_quests(res):
        """
        Gets quest data on almost any page
        """
        text = Extractor._extract_text_content(res)
        if not text:
            return None
        
        get_quests = re.search(r'Quests.setQuestData\((\{.+?\})\);', text)
        if get_quests:
            result = json.loads(get_quests.group(1), strict=False)
            for quest in result:
                data = result[quest]
                if data['goals_completed'] == data['goals_total']:
                    return quest
        return None

    @staticmethod
    def get_quest_rewards(res):
        """
        Detects if there are rewards available for quests
        """
        text = Extractor._extract_text_content(res)
        if not text:
            return []
        
        get_rewards = re.search(r'RewardSystem\.setRewards\(\s*(\[\{.+?\}\]),', text)
        rewards = []
        if get_rewards:
            result = json.loads(get_rewards.group(1), strict=False)
            for reward in result:
                if reward['status'] == "unlocked":
                    rewards.append(reward)
        # Return all off them
        return rewards

    @staticmethod
    def map_data(res):
        """
        Detects other villages on the map page
        """
        text = Extractor._extract_text_content(res)
        if not text:
            return []
        
        data = re.search(r'(?s)TWMap.sectorPrefech = (\[(.+?)\]);', text)
        if data:
            result = json.loads(data.group(1), strict=False)
            return result

    @staticmethod
    def smith_data(res):
        """
        Gets smith data
        """
        text = Extractor._extract_text_content(res)
        if not text:
            return None
        
        data = re.search(r'(?s)BuildingSmith.techs = (\{.+?\});', text)
        if data:
            result = json.loads(data.group(1), strict=False)
            return result
        return None

    @staticmethod
    def premium_data(res):
        """
        Detects data on the premium exchange page
        """
        text = Extractor._extract_text_content(res)
        if not text:
            return None
        
        data = re.search(r'(?s)PremiumExchange.receiveData\((.+?)\);', text)
        if data:
            result = json.loads(data.group(1), strict=False)
            return result
        return None

    @staticmethod
    def recruit_data(res):
        """
        Fetches recruit data for the current building
        """
        text = Extractor._extract_text_content(res)
        if not text:
            return None
        
        data = re.search(r'(?s)unit_managers.units = (\{.+?\});', text)
        if data:
            raw = data.group(1)
            quote_keys_regex = r'([\{\s,])(\w+)(:)'
            processed = re.sub(quote_keys_regex, r'\1"\2"\3', raw)
            result = json.loads(processed, strict=False)
            return result

    @staticmethod
    def units_in_village(res):
        """
        Detects all units in the village
        """
        text = Extractor._extract_text_content(res)
        if not text:
            return []
        
        matches = re.search(r'<table id="units_home".*?</tr>(.*?)</tr>', text, re.DOTALL)
        # We get the start of the table and grab the 2nd row (Where "From this village" troops are located)
        if matches:
            table_content = matches.group(1)
            unit_matches = re.findall(r'class=\'unit-item unit-item-(.*?)\'[^>]*>(\d+)</td>', table_content)
            # Find all the tuples (name, quantity) under the class "unit-item unit-item-*troop_name*"
            units = [(re.sub(r'\s*tooltip\s*', '', unit_name), unit_quantity) for unit_name, unit_quantity in
                     unit_matches if int(unit_quantity) > 0]
            # Filter units with quantity = 0, also for the Paladin,
            # the name would be "knight tooltip", so we had to remove that.
            return units
        return []

    @staticmethod
    def active_building_queue(res):
        """
        Detects queued building entries
        """
        text = Extractor._extract_text_content(res)
        if not text:
            return 0
        
        builder = re.search('(?s)<table id="build_queue"(.+?)</table>', text)
        if not builder:
            return 0

        return builder.group(1).count('<a class="btn btn-cancel"')

    @staticmethod
    def active_recruit_queue(res):
        """
        Detects active recruitment entries
        """
        text = Extractor._extract_text_content(res)
        if not text:
            return []
        
        builder = re.findall(r'(?s)TrainOverview\.cancelOrder\((\d+)\)', text)
        return builder

    @staticmethod
    def village_ids_from_overview(res):
        """
        Fetches villages from the overview page
        """
        text = Extractor._extract_text_content(res)
        if not text:
            return []
        
        villages = re.findall(r'<span class="quickedit-vn" data-id="(\w+)"', text)
        return list(set(villages))

    @staticmethod
    def units_in_total(res):
        """
        Gets total amount of units in a village
        """
        text = Extractor._extract_text_content(res)
        if not text:
            return []
        
        # hide units from other villages
        text = re.sub(r'(?s)<span class="village_anchor.+?</tr>', '', text)
        data = re.findall(r'(?s)class=\Wunit-item unit-item-([a-z]+)\W.+?(\d+)</td>', text)
        return data

    @staticmethod
    def attack_form(res):
        """
        Detects input fiels in the attack form
        ... because there are many :)
        """
        text = Extractor._extract_text_content(res)
        if not text:
            return []
        
        data = re.findall(r'(?s)<input.+?name="(.+?)".+?value="(.*?)"', text)
        return data

    @staticmethod
    def attack_duration(res):
        """
        Detects the duration of an attack
        """
        text = Extractor._extract_text_content(res)
        if not text:
            return 0
        
        data = re.search(r'<span class="relative_time" data-duration="(\d+)"', text)
        if data:
            return int(data.group(1))
        return 0

    @staticmethod
    def report_table(res):
        """
        Fetches information from a report
        """
        text = Extractor._extract_text_content(res)
        if not text:
            return []
        
        data = re.findall(r'(?s)class="report-link" data-id="(\d+)"', text)
        return data

    @staticmethod
    def get_daily_reward(res):
        """
        Detects if there are unopened daily rewards
        """
        text = Extractor._extract_text_content(res)
        if not text:
            return None
        
        get_daily = re.search(r'DailyBonus.init\((\s+\{.*\}),', res)
        res = json.loads(get_daily.group(1))
        reward_count_unlocked = str(res["reward_count_unlocked"])
        if reward_count_unlocked and res["chests"][reward_count_unlocked]["is_collected"]:
            return reward_count_unlocked
        return None

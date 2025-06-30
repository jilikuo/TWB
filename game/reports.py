"""
Report management
"""
import json
import logging
import re
import os
import locale
import random

from datetime import datetime, timedelta

from core.request import Delay
from core.extractors import Extractor
from core.filemanager import FileManager


class ReportManager:
    """
    Class to "efficiently" manage reports
    """
    wrapper = None
    village_id = None
    game_state = None
    logger = None
    last_reports = {}

    def __init__(self, wrapper=None, village_id=None):
        """
        Creates the report manager
        """
        self.wrapper = wrapper
        self.village_id = village_id

    def has_resources_left(self, vid):
        """
        Checks if there are any resources left after farm
        Used by the farm manager script
        """
        possible_reports = []
        for repid in self.last_reports:
            entry = self.last_reports[repid]
            if vid == entry["dest"] and entry["extra"].get("when", None):
                possible_reports.append(entry)
        # self.logger.debug(f"Considered {len(possible_reports)} reports")
        if len(possible_reports) == 0:
            return False, {}

        def highest_when(attack):
            """
            Converts the date of an attack when resource gains were high
            """
            return datetime.fromtimestamp(int(attack["extra"]["when"]))

        entry = max(possible_reports, key=highest_when)
        self.logger.debug("This is the newest? %s", datetime.fromtimestamp(int(entry["extra"]["when"])))
        if entry["extra"].get("resources", None):
            return True, entry["extra"]["resources"]
        return False, {}

    def safe_to_engage(self, vid):
        """
        Calculates if a village is safe to engage without custom interaction
        Just sending a 0 losses attack overrides this behaviour
        """
        for repid in self.last_reports:
            entry = self.last_reports[repid]
            if vid == entry["dest"]:
                if entry["type"] == "attack" and entry["losses"] == {}:
                    return 1
                # This 'try' code should handle problematic spy
                #reports, probably should be altered/removed if 
                #the issue got resolved.    
                try:
                    if (
                            entry["type"] == "scout"
                            and entry["losses"] == {}
                            and (
                            entry["extra"]["defence_units"] == {}
                            or entry["extra"]["defence_units"]
                            == entry["extra"]["defence_losses"]
                    )
                    ):
                        return 1
                except KeyError:
                    self.logger.debug(f"Report {repid} missing 'defence_units'. Checking for misclassification...")                    
                    try: 
                        if 'spy' not in entry["extra"]["units_sent"]:
                            self.logger.info(f"OVERRIDE: Report {repid} was misclassified as scout (no spies sent). Forcing attack as safe.")
                            return 1
                        else: 
                            self.logger.warning(f"Report {repid} is a failed scout mission (all spies lost). Treating as unsafe.")
                        
                    except KeyError:
                        self.logger.error(f"Report {repid} is *probably* broken or corrupted, missing both 'defence_units' and 'units_sent'. Treating as unsafe.")                             
                        return 0

                if entry["losses"] != {}:
                    # Acceptable losses for attacks
                    print(f'Units sent: {entry["extra"]["units_sent"]}')
                    print(f'Units lost: {entry["losses"]}')

                for sent_type in entry["extra"]["units_sent"]:
                    amount = entry["extra"]["units_sent"][sent_type]
                    if sent_type in entry["losses"]:
                        if amount == entry["losses"][sent_type]:
                            return 0  # Lost all units!
                        elif entry["losses"][sent_type] <= 1:
                            # Allow to lose 1 unit (luck depended)
                            return 1  # Lost 'just' one unit

                if entry["losses"] != {}:
                    return 0  # Disengage if anything was lost!
        return -1

    def read(self, page=0, full_run=False):
        """
        Read some (or all if you like) reports
        """
        if not self.logger:
            self.logger = logging.getLogger("Reports")

        if len(self.last_reports) == 0:
            self.logger.info("First run, cleaning up old reports...")
            ReportCache.cache_cleanup()
            self.logger.info("Re-reading cache entries...")
            self.last_reports = ReportCache.cache_grab()
            self.logger.info("Got %d reports from cache", len(self.last_reports))
        offset = page * 12
        url = f"game.php?village={self.village_id}&screen=report&mode=all"
        if page > 0:
            url += f"&from={offset}"
        result = self.wrapper.get_url(url)
        self.game_state = Extractor.game_state(result)
        current_report = 0

        ids = Extractor.report_table(result)
        for report_id in ids:
            if report_id in self.last_reports:
                continue
            current_report += 1
            url = f"game.php?village={self.village_id}&screen=report&mode=all&group_id=0&view={report_id}"

            '''
            
            #TODO: Consider using this to reduce workload. I still need to understand the uses of the reports data, if reports are
            # used mostly for statistics, this would mean a reduced accuracy, but faster processing. In that case, I would reccommend using this.
            
            if random.randint(0, 100) < 15:
                self.logger.debug(
                    f"Skipping report {report_id} to reduce workload. 3% chance. You might want to increase that if you attack the same villages thousands of times daily."
                )
                continue
            
            '''

            if random.randint(0, 100) < 8:
                data = self.wrapper.get_url(url, delay=Delay(min=0.25, max=2.5)) # Increased delay for 8% of reports
            elif current_report % 15 == 0:
                data = self.wrapper.get_url(url, delay=Delay(min=1, max=5)) # Guaranteed delay increase for every 15 reports 
            else:
                data = self.wrapper.get_url(url, delay = Delay(min=0.03, max=0.33)) # Decreased delay for faster processing.
            
            
            

            get_type = re.search(r'class="report_(\w+)', data.text)
            if get_type:
                report_type = get_type.group(1)
                if report_type == "ReportAttack":
                    self.attack_report(data.text, report_id)
                    continue

                else:
                    res = self.put(report_id, report_type=report_type)
                    self.last_reports[report_id] = res
        if full_run and page < 20:
            page += 1
            self.logger.debug(
                "%d new reports where added, also checking page %d", new, page
            )
            return self.read(page, full_run=full_run)

    def re_unit(self, inp):
        """
        No idea why I made this and what it does
        Guessing reading a line of units?
        """
        output = {}
        for row in inp:
            k, v = row
            if int(v) > 0:
                output[k] = int(v)
        return output

    def re_building(self, inp):
        """
        Read building levels from a report entry
        """
        output = {}
        for row in inp:
            k = row["id"]
            v = row["level"]
            if int(v) > 0:
                output[k] = int(v)
        return output

    def attack_report(self, report, report_id):
        """
        A report where we attacked a village
        """
        from_village = None
        from_player = None

        to_village = None
        to_player = None

        extra = {}
        losses = {}

        pattern = r'(?si)Data da batalha\s*</td>\s*<td>\s*(.+?)<'
        match = re.search(pattern, report)

        timestamp_str = None
        if match:
            timestamp_str = match.group(1).strip()

        if timestamp_str:
            try:
                date_format = "%b. %d, %Y %H:%M:%S"
                parsed_datetime = datetime.strptime(timestamp_str, date_format)
                extra["when"] = int(parsed_datetime.timestamp())

            except ValueError:
                try:
                    self.logger.warning(
                        f"System locale failed. Trying to force pt_BR locale {report_id}"
                        )
                    locale.setlocale(locale.LC_TIME, 'pt_BR.UTF-8')
                    parsed_datetime = datetime.strptime(timestamp_str, date_format)
                    extra["when"] = int(parsed_datetime.timestamp())
                    self.logger.debug(
                        f"Report {report_id}: Found 'when' data with forced pt_BR locale: {datetime.fromtimestamp(extra['when'])}"
                        )
                    self.logger.debug("Undoing forced locale change...")
                    locale.setlocale(locale.LC_TIME, '')

                except (ValueError, locale.Error) as e:
                    self.logger.error(f"Report {report_id}: Failed to read timestamp '{timestamp_str}'. Verify localization issues. Error: {e}")
        else:
            self.logger.warning(f"Report {report_id}: Could not find expected format timestamp (ex: jun. 19, 2025 14:55:04).")

        attacker = re.search(r'(?s)(<table id="attack_info_att".+?</table>)', report)
        if attacker:
            attacker_data = re.search(
                r'data-player="(\d+)" data-id="(\d+)"', attacker.group(1)
            )
            if attacker_data:
                from_player = attacker_data.group(1)
                from_village = attacker_data.group(2)
                units = re.search(
                    r'(?s)<table id="attack_info_att_units"(.+?)</table>',
                    attacker.group(1),
                )
                if units:
                    sent_units = re.findall("(?s)<tr>(.+?)</tr>", units.group(1))
                    extra["units_sent"] = self.re_unit(
                        Extractor.units_in_total(sent_units[0])
                    )
                    if len(sent_units) == 2:
                        extra["units_losses"] = self.re_unit(
                            Extractor.units_in_total(sent_units[1])
                        )
                        if from_player == self.game_state["player"]["id"]:
                            losses = extra["units_losses"]

        defender = re.search(r'(?s)(<table id="attack_info_def".+?</table>)', report)
        if defender:
            defender_data = re.search(
                r'data-player="(\d+)" data-id="(\d+)"', defender.group(1)
            )
            if defender_data:
                to_player = defender_data.group(1)
                to_village = defender_data.group(2)
                units = re.search(
                    r'(?s)<table id="attack_info_def_units"(.+?)</table>',
                    defender.group(1),
                )
                if units:
                    def_units = re.findall("(?s)<tr>(.+?)</tr>", units.group(1))
                    extra["defence_units"] = self.re_unit(
                        Extractor.units_in_total(def_units[0])
                    )
                    if len(def_units) == 2:
                        extra["defence_losses"] = self.re_unit(
                            Extractor.units_in_total(def_units[1])
                        )
                        if to_player == self.game_state["player"]["id"]:
                            losses = extra["defence_losses"]
        results = re.search(r'(?s)(<table id="attack_results".+?</table>)', report)
        report = report.replace('<span class="grey">.</span>', "")
        if results:
            loot = {}
            for loot_entry in re.findall(
                    r'<span class="icon header (wood|stone|iron)".+?</span>(\d+)', report
            ):
                loot[loot_entry[0]] = loot_entry[1]
            extra["loot"] = loot
            self.logger.info("attack report %s -> %s", from_village, to_village)

        attack_type = "attack"

        if extra.get("units_sent") and list(extra["units_sent"].keys()) == ["spy"]:
            attack_type = "scout"
            self.logger.info("Classified report %s as 'scout' based on units sent.", report_id)

        if attack_type == "scout":
            scout_results = re.search(
                r'(?s)(<table id="attack_spy_resources".+?</table>)', report
            )
            if scout_results:
                self.logger.info("scout report %s -> %s", from_village, to_village)
                scout_buildings = re.search(
                    r'(?s)<input id="attack_spy_building_data" type="hidden" value="(.+?)"',
                    report,
                )
                if scout_buildings:
                    raw = scout_buildings.group(1).replace("&quot;", '"')
                    extra["buildings"] = self.re_building(json.loads(raw))
                found_res = {}
                for loot_entry in re.findall(
                        r'<span class="icon header (wood|stone|iron)".+?</span>(\d+)', scout_results.group(1)
                ):
                    found_res[loot_entry[0]] = loot_entry[1]
                extra["resources"] = found_res
                units_away = re.search(
                    r'(?s)(<table id="attack_spy_away".+?</table>)', report
                )
                if units_away:
                    data_away = self.re_unit(Extractor.units_in_total(units_away.group(1)))
                    extra["units_away"] = data_away
            
        res = self.put(
            report_id, attack_type, from_village, to_village, data=extra, losses=losses
        )
        self.last_reports[report_id] = res
        return True

    def put(
            self,
            report_id,
            report_type,
            origin_village=None,
            dest_village=None,
            losses={},
            data={},
    ):
        """
        Creates a report file
        """
        output = {
            "type": report_type,
            "origin": origin_village,
            "dest": dest_village,
            "losses": losses,
            "extra": data,
        }
        ReportCache.set_cache(report_id, output)
        self.logger.info(
            "Processed %s report with id %s", report_type, str(report_id)
        )
        return output


class ReportCache:
    """
    File cache for local reports
    """
    @staticmethod
    def get_cache(report_id):
        """
        Reads a report entry
        """
        return FileManager.load_json_file(f"cache/reports/{report_id}.json")

    @staticmethod
    def set_cache(report_id, entry):
        """
        Creates a report entry
        """
        FileManager.save_json_file(entry, f"cache/reports/{report_id}.json")

    @staticmethod
    def cache_grab():
        """
        Reads all locally stored reports
        """
        output = {}

        for existing in FileManager.list_directory("cache/reports", ends_with=".json"):
            output[existing.replace(".json", "")] = FileManager.load_json_file(f"cache/reports/{existing}")
        return output

    @staticmethod
    def cache_cleanup(max_age_days=5):
        """
        Automatically removes reports where the attack itself happened more
        than `max_age_days` ago.
        """
        expiry_timestamp = (datetime.now() - timedelta(days=max_age_days)).timestamp()
        report_dir = "cache/reports"
        logger = logging.getLogger("Reports")

        if not os.path.exists(report_dir):
            return

        removed_count = 0
        for filename in FileManager.list_directory(report_dir, ends_with=".json"):
            filepath = os.path.join(report_dir, filename)

            try:
                report = FileManager.load_json_file(filepath)
                if not "extra" in report:
                    continue

                attack_timestamp = report.get("extra", {}).get("when")
                if attack_timestamp is None:
                    continue

                attack_timestamp = float(attack_timestamp)

                if attack_timestamp < expiry_timestamp:
                    FileManager.remove_file(filepath)
                    removed_count += 1
                    continue

            except Exception as e:
                logger.warning(
                    f"Error processing {filename} during clreanup: {e}. Skipping file."
                    )

        if removed_count > 0:
            logger.info(
                f"Removed {removed_count} old reports from cache"
                )
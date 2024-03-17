import os
import re
from os.path import join

from app.drivers.tools.localize.AbstractLocalizeTool import AbstractLocalizeTool


class CrashRepair(AbstractLocalizeTool):
    error_messages = ["aborted", "core dumped", "runtime error", "segmentation fault"]

    def __init__(self):
        self.name = os.path.basename(__file__)[:-3].lower()
        super().__init__(self.name)
        self.image_name = "rshariffdeen/crashrepair:tool"

    def generate_conf_file(self, bug_info):
        config_script = bug_info.get(self.key_config_script, None)
        if not config_script:
            self.error_exit(f"{self.name} requires a configuration script as input")

        repair_conf_path = join(self.dir_expr, "crashrepair.conf")
        conf_content = []
        if self.key_exploit_list not in bug_info:
            self.error_exit("CrashRepair requires a proof of concept")
        poc_list = bug_info[self.key_exploit_list]
        poc_abs_list = [join(self.dir_setup, x) for x in poc_list]
        build_command = bug_info.get(self.key_build_command, None)
        if build_command is None:
            build_script = bug_info.get(self.key_build_script, None)
            if not build_script:
                self.error_exit(
                    f"{self.name} requires a build script or build command" f"as input"
                )
            build_command = f"{self.dir_setup}/{build_script}"

        conf_content.append("dir_exp:{}\n".format(self.dir_expr))
        conf_content.append("tag_id:{}\n".format(bug_info[self.key_bug_id]))
        conf_content.append("src_directory:src\n")
        conf_content.append("binary_path:{}\n".format(bug_info[self.key_bin_path]))
        conf_content.append(
            f"config_command:CC=crepair-cc CXX=crepair-cxx {self.dir_setup}/{config_script}\n"
        )
        conf_content.append(
            "build_command:CC=crepair-cc CXX=crepair-cxx {}\n".format(build_command)
        )
        if self.key_crash_cmd not in bug_info:
            self.error_exit("CrashRepair requires a test input list")

        conf_content.append("test_input_list:{}\n".format(bug_info[self.key_crash_cmd]))
        conf_content.append("poc_list:{}\n".format(",".join(poc_abs_list)))
        self.append_file(conf_content, repair_conf_path)
        return repair_conf_path

    def run_localization(self, bug_info, repair_config_info):
        super(CrashRepair, self).run_localization(bug_info, repair_config_info)
        conf_path = self.generate_conf_file(bug_info)
        timeout_h = str(repair_config_info[self.key_timeout])
        timeout_m = 60 * int(timeout_h)
        timeout_validation = int(timeout_m * 0.75)
        timeout_test = 30
        additional_tool_param = repair_config_info[self.key_tool_params]
        patch_limit = 10
        bug_json_path = self.dir_expr + "/bug.json"
        self.timestamp_log_start()
        repair_command = (
            f"bash -c 'stty cols 100 && stty rows 100 && timeout -k 5m {str(timeout_h)}h "
            f"crepair --conf={conf_path} "
            f" {additional_tool_param} '"
        )

        status = self.run_command(repair_command, log_file_path=self.log_output_path)

        self.process_status(status)

        self.timestamp_log_end()
        self.emit_highlight("log file: {0}".format(self.log_output_path))

    def save_artifacts(self, dir_info):
        list_artifact_dirs = ["/CrashRepair/output/", "/CrashRepair/logs/"]
        list_artifact_files = [
            f"/CrashRepair/output/{self.stats.bug_info[self.key_bug_id]}/analysis.json"
        ]
        for d in list_artifact_dirs:
            copy_command = f"cp -rf {d} {self.dir_output}"
            self.run_command(copy_command)
        for f in list_artifact_files:
            copy_command = f"cp {f} {self.dir_output}"
            self.run_command(copy_command)
        super(CrashRepair, self).save_artifacts(dir_info)
        return

    def analyse_output(self, dir_info, bug_id, fail_list):
        self.emit_normal("reading output")
        report_path = f"/CrashRepair/output/{bug_id}/analysis.json"
        report_json = self.read_json(report_path)

        count_fix_locs = 0
        count_src_files = 0
        count_fix_funcs = 0
        if report_json:
            localization_list = report_json.get("analysis_output")[0].get(
                "localization"
            )
            if localization_list:
                count_fix_locs = len(localization_list)
                src_files = set()
                fix_funcs = set()
                for l in localization_list:
                    src_files.add(l.get("source_file"))
                    fix_funcs.add(l.get("function"))
                count_fix_funcs = len(fix_funcs)
                count_src_files = len(src_files)

        # extract information from output log
        if not self.log_output_path or not self.is_file(self.log_output_path):
            self.emit_warning("no output log file found")
            return self.stats

        self.emit_highlight(f"output log file: {self.log_output_path}")

        if self.is_file(self.log_output_path):
            log_lines = self.read_file(self.log_output_path, encoding="iso-8859-1")
            self.stats.time_stats.timestamp_start = log_lines[0].rstrip()
            self.stats.time_stats.timestamp_end = log_lines[-1].rstrip()

            for line in log_lines:
                if any(err in line.lower() for err in self.error_messages):
                    self.stats.error_stats.is_error = True

        self.stats.fix_loc_stats.fix_locs = count_fix_locs
        self.stats.fix_loc_stats.source_files = count_src_files
        self.stats.fix_loc_stats.fix_funcs = count_fix_funcs
        return self.stats

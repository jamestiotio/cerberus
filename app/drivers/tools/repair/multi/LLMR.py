import os
import re
from os.path import join

from app.core import definitions
from app.drivers.tools.repair.AbstractRepairTool import AbstractRepairTool


class LLMR(AbstractRepairTool):
    def __init__(self):
        self.name = os.path.basename(__file__)[:-3].lower()
        super().__init__(self.name)
        self.image_name = "mirchevmp/llmr"

    def run_repair(self, bug_info, repair_config_info):
        super(LLMR, self).run_repair(bug_info, repair_config_info)
        """
            self.dir_logs - directory to store logs
            self.dir_setup - directory to access setup scripts
            self.dir_expr - directory for experiment
            self.dir_output - directory to store artifacts/output
        """

        timeout_h = str(repair_config_info[self.key_timeout])
        # Any communication based model works
        model = repair_config_info.get(self.key_tool_params, "gpt-4")

        if model == "":
            model = "gpt-4"

        passing_tests = ",".join(bug_info[self.key_passing_tests])
        failing_tests = ",".join(bug_info[self.key_failing_tests])

        self.run_command("mkdir -p {}".format(join(self.dir_output, "patches")))

        file = ""
        if self.key_localization in bug_info:
            file = bug_info[self.key_localization][0][self.key_fix_file]
            if bug_info[self.key_language] == "java" and not file.endswith(".java"):
                file = f"src/main/java/{file.replace('.', '/')}.java"
            self.emit_debug("LLMR will work on file {}".format(file))
        fl = ""

        if repair_config_info["fault_location"] == "auto":
            fl = "-do-fl"
        elif repair_config_info["fault_location"] == "line":
            fl_info = list(
                map(
                    lambda line: f"{bug_info[self.key_fix_file]}::{line},1\n",
                    bug_info[self.key_fix_lines],
                )
            )
            self.emit_debug(f"File localization info: {fl_info}")
            fl_path = join(self.dir_output, "fl_data.txt")
            self.write_file(fl_info, fl_path)
            fl = f"-fl-data {fl_path}"

        # start running
        self.timestamp_log_start()
        llmr_command = "timeout -k 5m {timeout_h}h python3 /tool/repair.py {fl} --project-path {project_path} -model {model} {file} {reference_file} {bug_description} {build_script} -output {output_loc} -patches {patch_count} -test {test_script} {binary_path} {passing_tests} {failing_tests} {debug} {language}".format(
            timeout_h=timeout_h,
            patch_count=5,
            project_path=join(self.dir_expr, "src"),
            build_script="-build {}".format(
                join(self.dir_setup, bug_info[self.key_build_script])
            )
            if (
                self.key_build_script in bug_info
                and bug_info[self.key_build_script] != ""
            )
            else "",
            output_loc=self.dir_output,
            test_script=join(self.dir_setup, bug_info[self.key_test_script]),
            file="-file {}".format(file) if file else "",
            model=model,
            passing_tests="-passing-tests {}".format(passing_tests)
            if passing_tests != ""
            else " ",
            failing_tests="-failing-tests {}".format(failing_tests)
            if failing_tests != ""
            else " ",
            binary_path="-binary-loc {}".format(bug_info[self.key_bin_path])
            if self.key_bin_path in bug_info
            else " ",
            debug="-d" if self.is_debug else "",
            reference_file="-reference {}".format(
                bug_info[definitions.KEY_REFERENCE_FILE]
            )
            if definitions.KEY_REFERENCE_FILE in bug_info
            else "",
            bug_description="-description {}".format(
                join(self.dir_setup, bug_info["bug_description"])
            )
            if "bug_description" in bug_info
            else "",
            language="-lang {}".format(bug_info[self.key_language])
            if self.key_language in bug_info
            else "",
            fl=fl,
        )
        status = self.run_command(
            llmr_command, self.log_output_path, join(self.dir_expr, "src")
        )

        self.process_status(status)

        self.timestamp_log_end()
        self.emit_highlight("log file: {0}".format(self.log_output_path))

    def save_artifacts(self, dir_info):
        """
        Save useful artifacts from the repair execution
        output folder -> self.dir_output
        logs folder -> self.dir_logs
        The parent method should be invoked at last to archive the results
        """
        # remove traces that are not necessary
        remove_command = (
            f"rm -rf {self.dir_output}/failing_traces {self.dir_output}/passing_traces "
        )
        self.exec_command(remove_command)
        super().save_artifacts(dir_info)

    def analyse_output(self, dir_info, bug_id, fail_list):
        """
        analyse tool output and collect information
        output of the tool is logged at self.log_output_path
        information required to be extracted are:

            self.stats.patches_stats.non_compilable
            self.stats.patches_stats.plausible
            self.stats.patches_stats.size
            self.stats.patches_stats.enumerations
            self.stats.patches_stats.generated

            self.stats.time_stats.total_validation
            self.stats.time_stats.total_build
            self.stats.time_stats.timestamp_compilation
            self.stats.time_stats.timestamp_validation
            self.stats.time_stats.timestamp_plausible
        """
        self.emit_normal("reading output")

        # count number of patch files
        list_output_dir = self.list_dir(self.dir_patch)
        self.stats.patch_stats.generated = len(
            [name for name in list_output_dir if ".patch" in name]
        )

        # extract information from output log
        if not self.log_output_path or not self.is_file(self.log_output_path):
            self.emit_warning("no output log file found")
            return self.stats

        self.emit_highlight(f"output log file: {self.log_output_path}")

        if self.is_file(self.log_output_path):
            log_lines = self.read_file(self.log_output_path, encoding="iso-8859-1")

            for line in log_lines:
                if re.match("Patch .* is Plausible", line):
                    self.stats.patch_stats.plausible += 1

        return self.stats

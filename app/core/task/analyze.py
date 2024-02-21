import threading
import time
import traceback
from typing import Any
from typing import Dict
from typing import Optional

from app.core import definitions
from app.core import emitter
from app.core import parallel
from app.core import utilities
from app.core import values
from app.core.task.TaskStatus import TaskStatus
from app.core.task.typing.DirectoryInfo import DirectoryInfo
from app.core.task.typing.TaskType import TaskType
from app.drivers.tools.analyze.AbstractAnalyzeTool import AbstractAnalyzeTool


def run_analysis(
    dir_info: DirectoryInfo,
    experiment_info,
    tool: AbstractAnalyzeTool,
    analysis_config_info: Dict[str, Any],
    container_id: Optional[str],
    benchmark_name: str,
):
    experiment_info[definitions.KEY_BENCHMARK] = benchmark_name

    if analysis_config_info[definitions.KEY_CONFIG_FIX_LOC] == "file":
        for localization_entry in experiment_info[definitions.KEY_LOCALIZATION]:
            del localization_entry[definitions.KEY_CONFIG_FIX_LOC]
    elif analysis_config_info[definitions.KEY_CONFIG_FIX_LOC] == "line":
        for localization_entry in experiment_info[definitions.KEY_LOCALIZATION]:
            fix_source_file = str(localization_entry.get(definitions.KEY_FIX_FILE, ""))
            fix_line_numbers = list(
                map(str, localization_entry.get(definitions.KEY_FIX_LINES, []))
            )
            localization_entry[definitions.KEY_FIX_FILE] = "{}:{}".format(
                fix_source_file, ",".join(fix_line_numbers)
            )
    elif analysis_config_info[definitions.KEY_CONFIG_FIX_LOC] == "auto":
        if definitions.KEY_LOCALIZATION in experiment_info:
            del experiment_info[definitions.KEY_LOCALIZATION]

    test_ratio = float(analysis_config_info[definitions.KEY_CONFIG_TEST_RATIO])
    test_timeout = int(
        analysis_config_info.get(definitions.KEY_CONFIG_TIMEOUT_TESTCASE, 10)
    )
    passing_test_identifiers_list = experiment_info.get(
        definitions.KEY_PASSING_TEST, []
    )
    if isinstance(passing_test_identifiers_list, str):
        passing_test_identifiers_list = passing_test_identifiers_list.split(",")
    failing_test_identifiers_list = experiment_info.get(
        definitions.KEY_FAILING_TEST, []
    )
    if isinstance(failing_test_identifiers_list, str):
        failing_test_identifiers_list = failing_test_identifiers_list.split(",")
    pass_test_count = int(len(passing_test_identifiers_list) * test_ratio)
    experiment_info[definitions.KEY_PASSING_TEST] = passing_test_identifiers_list[
        :pass_test_count
    ]
    experiment_info[definitions.KEY_FAILING_TEST] = failing_test_identifiers_list
    experiment_info[definitions.KEY_CONFIG_TIMEOUT_TESTCASE] = test_timeout
    tool.update_info(container_id, values.only_instrument, dir_info, experiment_info)
    tool.process_tests(dir_info, experiment_info)
    try:
        tool.run_analysis(experiment_info, analysis_config_info)
        if values.experiment_status.get(TaskStatus.NONE) == TaskStatus.NONE:
            values.experiment_status.set(TaskStatus.SUCCESS)
    except Exception as ex:
        values.experiment_status.set(TaskStatus.FAIL_IN_TOOL)
        emitter.error(f"\t\t\t[ERROR][{tool.name}]: {ex}")
        emitter.error(f"\t\t\t[ERROR][{tool.name}]: {traceback.format_exc()}")


def analyze_all(
    dir_info: Any,
    experiment_info: Dict[str, Any],
    analyze_tool: AbstractAnalyzeTool,
    analysis_config_info,
    container_id: Optional[str],
    benchmark_name: str,
):
    consume_thread = None
    tool_thread = None
    if not values.ui_active:
        parallel.initialize()

    if definitions.KEY_CONFIG_ANALYZE_TIMEOUT in analysis_config_info:
        analysis_config_info[definitions.KEY_CONFIG_TIMEOUT] = analysis_config_info[
            definitions.KEY_CONFIG_FUZZ_TIMEOUT
        ]

    time_duration = float(analysis_config_info.get(definitions.KEY_CONFIG_TIMEOUT, 1))
    total_timeout = time.time() + 60 * 60 * time_duration

    final_status = [TaskStatus.NONE]

    if values.use_valkyrie:
        values.running_tool = True

    if values.ui_active:
        run_analysis(
            dir_info,
            experiment_info,
            analyze_tool,
            analysis_config_info,
            container_id,
            benchmark_name,
        )
    else:

        def analyze_wrapped(
            dir_info,
            experiment_info,
            analyze_tool: AbstractAnalyzeTool,
            analyze_config_info,
            container_id: Optional[str],
            benchmark_name: str,
            task_profile_id: str,
            job_identifier: str,
            task_type: TaskType,
            final_status,
        ):
            """
            Pass over some fields as we are going into a new thread
            """
            values.task_type.set(task_type)
            values.current_task_profile_id.set(task_profile_id)
            values.job_identifier.set(job_identifier)
            run_analysis(
                dir_info,
                experiment_info,
                analyze_tool,
                analyze_config_info,
                container_id,
                benchmark_name,
            )
            final_status[0] = values.experiment_status.get(TaskStatus.SUCCESS)

        tool_thread = threading.Thread(
            target=analyze_wrapped,
            args=(
                dir_info,
                experiment_info,
                analyze_tool,
                analysis_config_info,
                container_id,
                benchmark_name,
                values.current_task_profile_id.get("NA"),
                values.job_identifier.get("NA"),
                values.task_type.get(None),
                final_status,
            ),
            name="Wrapper thread for analysis {} {} {} {}".format(
                analyze_tool.name, analyze_tool.tool_tag, benchmark_name, container_id
            ),
        )
        tool_thread.start()

        if not tool_thread:
            utilities.error_exit(
                "\t\t[framework] tool thread was not created somehow??"
            )
        wait_time = 5.0
        if time.time() <= total_timeout:
            wait_time = total_timeout - time.time()
        tool_thread.join(wait_time)
        if tool_thread.is_alive():
            emitter.highlight(
                "\t\t\t[framework] thread for {} {} is not done, setting event to kill thread.".format(
                    analyze_tool.name, analyze_tool.tool_tag
                )
            )
            event = threading.Event()
            event.set()
            # The thread can still be running at this point. For example, if the
            # thread's call to isSet() returns right before this call to set(), then
            # the thread will still perform the full 1 second sleep and the rest of
            # the loop before finally stopping.
        else:
            emitter.highlight(
                "\t\t\t[framework] thread for {}{} has already finished.".format(
                    analyze_tool.name, analyze_tool.tool_tag
                )
            )

        # Thread can still be alive at this point. Do another join without a timeout
        # to verify thread shutdown.
        tool_thread.join()
        values.experiment_status.set(final_status[0])
        # if tool.log_output_path:
        #     timestamp_command = "echo $(date -u '+%a %d %b %Y %H:%M:%S %p') >> " + tool.log_output_path
        #     utilities.execute_command(timestamp_command)

    values.running_tool = False
    if values.use_valkyrie:
        emitter.normal("\t\t\twaiting for validation pool")
        parallel.wait_validation()
        emitter.normal("\t\t\twaiting for consumer pool")
        if consume_thread:
            consume_thread.join()
    # for t in tool_list:
    #     timestamp_command = "echo $(date -u '+%a %d %b %Y %H:%M:%S %p') >> " + t.log_output_path
    #     utilities.execute_command(timestamp_command)

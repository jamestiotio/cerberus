import hashlib
import json
import os
import shutil
import time
import traceback
from copy import deepcopy
from multiprocessing import Lock
from multiprocessing.pool import ThreadPool
from multiprocessing.synchronize import Lock as LockType
from os.path import basename
from os.path import dirname
from os.path import join
from queue import Queue
from typing import Any
from typing import Callable
from typing import cast
from typing import Dict
from typing import List
from typing import Optional
from typing import Set
from typing import Tuple
from typing import Union

from jsonschema import Draft7Validator
from watchdog.events import DirCreatedEvent
from watchdog.events import FileCreatedEvent
from watchdog.events import FileSystemEvent
from watchdog.observers import Observer

from app.core import configuration
from app.core import definitions
from app.core import reader
from app.core import utilities
from app.core import values
from app.core import writer
from app.core.main import create_task_identifier
from app.core.main import create_task_image_identifier
from app.core.metadata.MetadataValidationSchemas import general_section_schema
from app.core.task import task
from app.core.task.typing.CompositeSequence import CompositeSequence
from app.core.task.typing.DirectoryInfo import DirectoryInfo
from app.core.task.typing.TaskType import CompositeTaskType
from app.core.task.typing.TaskType import TaskType
from app.drivers.benchmarks.AbstractBenchmark import AbstractBenchmark
from app.drivers.tools.AbstractTool import AbstractTool
from app.drivers.tools.composite.AbstractCompositeTool import AbstractCompositeTool
from app.drivers.tools.composite.multi.basic.FileCreationHandler import (
    FileCreationHandler,
)
from app.drivers.tools.MockTool import MockTool

active_jobs_lock: LockType


# Due to the way python multiprocess works,
# we cannot pass a lock to the pool initializer by just seeting a
# field on the object, similarly to how it is done in the UI module
# (the UI module is using in process threads and the lock is not shared across process, has to be reworked).
# Instead, we need to use a global variable which is per process.
# This is not ideal, but it is the correct way to make it work.
def init_pool_processes(active_jobs_lock_x: LockType):
    global active_jobs_lock
    active_jobs_lock = active_jobs_lock_x


class BasicWorkflow(AbstractCompositeTool):
    key_task_tag: str = "task_tag"
    key_image_tag: str = "image_tag"
    key_real_type = "real_type"

    def __init__(self):
        self.name = basename(__file__)[:-3].lower()
        super().__init__(self.name)
        # preferably change to a container with the dependencies ready to reduce setup time
        self.image_name = "ubuntu:20.04"
        self.process_count = 16
        self.event_processor_count = 4
        self.exit_message = "quit"  # Message for terminating the flow
        self.exit_message_delayed = (
            "quit_delayed"  # Message for a termination that will happen after a delay
        )
        self.last_crash = 0
        self.active_jobs = 0

    def run_composite(
        self,
        dir_info: DirectoryInfo,
        benchmark: AbstractBenchmark,
        bug_info,  # Entry from  meta-data.json
        composite_config_info,  # Task Profile
        container_config_info,  # Container Profile
        run_index: str,  # Specific iteration of the workflow run
        hash: Any,  # Hash, to be used for unique locations
    ):
        """
        Entry point for the workflow.
        The function parses the composite sequence proivded in the composite_config_info
        and then starts an "initial tool" - fuzzer, localizer, repair tool, in that order of preference.
        Currently the system does not terminate a lot of things and this is left as a TODO
        """
        super(BasicWorkflow, self).run_composite(
            dir_info,
            benchmark,
            bug_info,
            composite_config_info,
            container_config_info,
            run_index,
            hash.hexdigest()[:8],
        )
        """
            self.dir_logs - directory to store logs
            self.dir_setup - directory to access setup scripts
            self.dir_expr - directory for experiment
            self.dir_output - directory to store artifacts/output
        """
        self.pool = ThreadPool(
            processes=self.process_count,
            initializer=init_pool_processes,
            initargs=(Lock(),),
        )
        self.message_queue: Queue[Union[str, FileSystemEvent]] = Queue()
        self.observer = Observer()
        self.cpu_queue: Queue[str] = Queue()
        # TODO implement gpu queue
        for i in range(min(self.process_count, composite_config_info[self.key_cpus])):
            self.cpu_queue.put(str(i))

        self.mutex = Lock()
        self.observed: Set[Any] = set()

        self.emit_debug(composite_config_info)
        composite_sequence: CompositeSequence = cast(
            CompositeSequence, composite_config_info[self.key_composite_sequence]
        )
        root_tool_tag = composite_config_info.get(definitions.KEY_TOOL_TAG, "")

        self.emit_normal("setting up workflow")
        self.emit_debug(composite_sequence)

        root_dir = join(
            values.dir_main,
            "composite_workspace",
            "run-{}".format(hash.hexdigest()[:8]),
        )
        os.makedirs(root_dir, exist_ok=True)
        self.root_dir = root_dir

        self.task_mappings = self.make_task_mappings(root_dir)
        self.bug_info = bug_info

        self.tool_map: Dict[
            CompositeTaskType, List[Tuple[AbstractTool, str, str, str]]
        ] = {}
        # TODO move tool to be generated dynamically
        for task_type, tools in composite_sequence.items():
            self.tool_map[task_type] = []
            for tool_info in tools:
                tag_fragments = []
                if root_tool_tag:
                    tag_fragments.append(root_tool_tag)

                tool_name = tool_info["name"]
                if tool_info.get("ignore", False):
                    self.emit_debug(f"Skip {tool_name}")
                    continue
                tool_params = tool_info.get("params", "")

                extra_tool_tag = tool_info.get("tag", "")
                if extra_tool_tag:
                    tag_fragments.append(extra_tool_tag)

                tool_tag = "-".join(tag_fragments)

                real_type = tool_info.get(
                    "type", task_type
                )  # override the type when in "special" (crash-analyze) types
                if tool_name == "mock":
                    tool = cast(AbstractTool, MockTool())
                else:
                    tool = configuration.load_tool(tool_name, real_type)
                    tool.tool_tag = tool_tag

                self.emit_debug(tool.bindings)
                tool.bindings = tool.bindings or {}
                tool.bindings.update(self.task_mappings[task_type])
                self.emit_debug(tool.bindings)

                tool.check_tool_exists()
                image_name = create_task_image_identifier(
                    benchmark,
                    tool,
                    bug_info,
                    tool_tag,
                )
                experiment_image_id = task.prepare_experiment(
                    benchmark,
                    bug_info,
                    composite_config_info[self.key_cpus],
                    [],
                    tool_tag,
                )
                task.prepare_experiment_tool(
                    experiment_image_id,
                    tool,
                    composite_config_info,
                    dir_info,
                    image_name,
                    bug_info,
                    tool_tag,
                )
                self.tool_map[task_type].append(
                    (tool, tool_params, tool_tag, real_type)
                )

        self.emit_highlight("Done with setup!")

        self.emit_highlight("Preparing watcher")
        watcher_handle = self.pool.apply_async(
            self.watcher, error_callback=self.error_callback_handler
        )

        self.emit_highlight("Preparing workers")
        for _ in range(self.event_processor_count):
            self.pool.apply_async(
                self.event_worker, error_callback=self.error_callback_handler
            )

        self.proto_args = (
            dir_info,
            benchmark,
            bug_info,
            composite_config_info,
            container_config_info,
            run_index,
            hash,
        )
        # start running
        self.timestamp_log_start()

        if not self.do_step(
            bug_info, None, None, ["analyze", "fuzz", "crash-analyze", "repair"]
        ):
            self.observer.stop()
            for _ in range(self.event_processor_count):
                self.message_queue.put("exit")
            self.emit_error("No supported starter for the process")

        watcher_handle.wait()
        self.pool.terminate()
        self.emit_highlight("Terminated")
        self.timestamp_log_end()
        self.emit_highlight("log file: {0}".format(self.log_output_path))

    def run_subtask(
        self,
        task_type: TaskType,
        dir_info: DirectoryInfo,
        benchmark: AbstractBenchmark,
        bug_info,  # Entry from  meta-data.json
        composite_config_info,  # Task Profile
        container_config_info,  # Container Profile
        run_index,  # Specific iteration of the workflow run
        hash: Any,  # Hash, to be used for unique locations
        tool: AbstractTool,
    ):
        """
        Common entry point for a subtask, we take the original task tag to not create new images.
        This flow assumes that the run_composite function has prepared all the tags beforehand in order to quickly start new jobs.
        """

        global active_jobs_lock
        with active_jobs_lock:
            self.active_jobs += 1
            self.emit_debug(f"Active jobs: {self.active_jobs}")

        cpu = None
        try:
            values.task_type.set(task_type)
            values.current_task_profile_id.set(composite_config_info["id"])
            values.current_container_profile_id.set(composite_config_info["id"])
            tool_tag = composite_config_info.get(self.key_task_tag, "")
            image_tag = composite_config_info.get(self.key_image_tag, "")
            image_name = create_task_image_identifier(
                benchmark,
                tool,
                bug_info,
                image_tag,
            )

            key = create_task_identifier(
                benchmark,
                composite_config_info,
                container_config_info,
                bug_info,
                tool,
                str(run_index),
                tool_tag,
            )
            values.job_identifier.set(key)

            # TODO track multiple cpus
            cpu = self.cpu_queue.get()

            with open(
                join(
                    list(
                        self.task_mappings[
                            composite_config_info[self.key_real_type]
                        ].keys()
                    )[0],
                    "cerberus_internal.json",
                ),
                "w",
            ) as f:
                self.emit_debug("Creating internal representation")
                f.write(
                    json.dumps(
                        {
                            "dir_info": task.generate_tool_dir_info(
                                benchmark.name,
                                bug_info[self.key_subject],
                                bug_info[self.key_bug_id],
                                hash,
                                key,
                                tool_tag,
                            ),
                            "bug_info": bug_info,
                        }
                    )
                )

            err, _ = task.run(
                benchmark,
                tool,
                bug_info,
                composite_config_info,
                container_config_info,
                key,
                [cpu],
                composite_config_info[self.key_gpus],
                run_index,
                image_name,
                hash,
                tool_tag,
            )
            if err:
                self.stats.error_stats.is_error = True
        except Exception as e:
            self.emit_warning(e)
            traceback.print_exc()
        finally:
            if cpu is not None:
                self.cpu_queue.put(cpu)

        with active_jobs_lock:
            self.active_jobs -= 1
            self.emit_debug(f"Active jobs: {self.active_jobs}")
            if self.active_jobs == 0:
                self.message_queue.put(self.exit_message_delayed)

    def error_callback_handler(self, e: BaseException):
        self.emit_error("I got an exception!")
        self.emit_warning(e)
        self.stats.error_stats.is_error = True
        traceback.print_exc()

    def watcher(self):
        event_handler = FileCreationHandler(self.message_queue)
        self.emit_highlight("Observing {}".format(self.root_dir))
        self.observer.schedule(event_handler, self.root_dir, recursive=True)
        self.observer.start()

        try:
            while self.observer.is_alive():
                self.observer.join(1)
        finally:
            self.observer.stop()
            self.observer.join()

    def pre_process_event(self, event: FileSystemEvent):
        if self.filter_event(event):
            # self.emit_debug("Did not filter {}".format(event))
            with self.mutex:
                if event.src_path not in self.observed:
                    self.observed.add(event.src_path)
                    new_file = True
                else:
                    new_file = False

            # self.emit_debug("Is new file? {}".format(new_file))
            if new_file:
                time.sleep(0.5)  # HACK: make sure file is written to
                return True
        # self.emit_debug("Filtered {}".format(event))
        return False

    def filter_event(self, event: FileSystemEvent):
        """
        Exclude commonly known files which are not a signal for an interesting change.
        Directories are ignored!
        """
        if event.is_directory:
            return False
        if basename(event.src_path) in [
            "README.txt",
            "fuzz_bitmap",
            ".cur_input",
            ".affinity",
            ".affinity_lock",
            "plot_data",
            ".synced",
            "cmdline",
            "trace.sh",
            ".fuzzer_stats_tmp",
            "cerberus_internal.json",
        ] or os.path.basename(os.path.normpath(dirname(event.src_path))) in [
            "benign_tests"
        ]:
            return False
        if ".state" in event.src_path or ".trace" in event.src_path:
            return False
        return True

    def process_event(self, event: FileSystemEvent):
        # self.emit_debug(f"Processing! {event}")
        if basename(event.src_path) == self.exit_message:
            for _ in range(self.process_count):
                self.emit_debug("Time to die")
                self.message_queue.put(self.exit_message)

        if basename(event.src_path) == "meta-data.json":
            for type, sub_root, handler in [
                ("Repair", self.repair_root, self.on_repair_finished),
                ("Analyze", self.analyze_root, self.on_analysis_finished),
                ("Localize", self.localize_root, self.on_localization_finished),
                ("Validate", self.validate_root, self.on_validation_finished),
                ("Select", self.select_root, self.on_selection_finished),
            ]:
                if os.path.commonprefix([event.src_path, sub_root]) == sub_root:
                    self.emit_highlight("{} update".format(type))
                    handler(event)
                    break
        else:
            if os.path.commonprefix([event.src_path, self.fuzz_root]) == self.fuzz_root:
                # self.emit_highlight("Fuzz Update")
                # self.emit_debug(dirname(event.src_path))
                if dirname(event.src_path).endswith("crashes"):
                    # self.emit_normal("Found a crash!")
                    self.pool.apply_async(
                        self.on_crash_found,
                        [event],
                        error_callback=self.error_callback_handler,
                    )
            elif (
                os.path.commonprefix([event.src_path, self.crash_analyze_root])
                == self.crash_analyze_root
            ):
                pass
            else:
                self.emit_warning("Ignoring file {}".format(event.src_path))
            # elif (
            #     os.path.commonprefix(
            #         [event.src_path, self.crash_analyze_root]
            #     )
            #     == list(self.task_mappings["crash-analyze"].keys())[0]
            # ):
            #     # self.emit_debug("Ignoring crash analysis update")
            #     pass

    def on_fuzzing_finished(self, res):
        try:
            base_dir = list(self.task_mappings["fuzz"].keys())[0]
            benign_dir = join(base_dir, "benign_tests")
            crash_dir = join(base_dir, "crashing_tests")

            subtask_hash = hashlib.sha1()
            subtask_hash.update(str(time.time()).encode("utf-8"))
            subtask_tag = subtask_hash.hexdigest()[:8]

            (base_setup, enhanced_setup) = self.get_setup_directories(
                self.fuzz_root, subtask_tag
            )

            self.emit_debug(f"Setup dir is {base_setup}")
            self.emit_debug(f"New setup dir is {enhanced_setup}")

            shutil.copytree(base_setup, enhanced_setup)
            os.makedirs(join(enhanced_setup, "benign_tests"), exist_ok=True)
            os.makedirs(join(enhanced_setup, "crashing_tests"), exist_ok=True)

            self.copy_tests(crash_dir, enhanced_setup, "crashing_tests")

            self.copy_tests(benign_dir, enhanced_setup, "benign_tests")

            bug_info_extension = reader.read_json(join(base_dir, "meta-data.json"))

            new_bug_info = self.merge_dict(
                self.bug_info,
                (
                    bug_info_extension[0]
                    if isinstance(bug_info_extension, list)
                    else bug_info_extension
                ),
            )

            writer.write_as_json(
                new_bug_info,
                join(
                    list(self.task_mappings["fuzz"].keys())[0],
                    f"meta-data-{subtask_tag}.json",
                ),
            )

            self.do_step(
                new_bug_info,
                subtask_hash,
                subtask_tag,
                ["crash-analyze", "localize", "repair"],
            )

        except Exception as e:
            self.emit_warning(e)
            traceback.print_exc()
        pass

    def on_crash_found(self, event: FileSystemEvent):
        try:
            crash_dir = dirname(event.src_path)
            benign_dir = join(dirname(crash_dir), "queue")
            current_time = int(time.time())

            if self.last_crash is not None and current_time - self.last_crash <= 1200:
                # self.emit_debug("Debouncing the crash")
                return

            self.last_crash = int(time.time())

            subtask_hash = hashlib.sha1()
            subtask_hash.update(str(time.time()).encode("utf-8"))
            subtask_tag = subtask_hash.hexdigest()[:8]

            base_setup = self.proto_args[0]["local"]["setup"]
            self.emit_debug(f"Base setup dir is {base_setup}")
            enhanced_setup = join(
                dirname(os.path.normpath(base_setup)),
                f"{basename(os.path.normpath(base_setup))}-{subtask_tag}",
            )
            self.emit_debug(f"New setup dir is {enhanced_setup}")

            shutil.copytree(base_setup, enhanced_setup)
            os.makedirs(join(enhanced_setup, "benign_tests"), exist_ok=True)
            os.makedirs(join(enhanced_setup, "crashing_tests"), exist_ok=True)

            shutil.copy(
                event.src_path,
                join(enhanced_setup, "crashing_tests", ""),
            )
            self.copy_tests(benign_dir, enhanced_setup, "benign_tests")

            new_bug_info = deepcopy(self.bug_info)

            new_bug_info[self.key_exploit_inputs] = [
                {"format": "raw", "dir": "crashing_tests"}
            ]
            new_bug_info[self.key_benign_inputs] = [
                {"format": "raw", "dir": "benign_tests"}
            ]
            new_bug_info["test_dir_abspath"] = self.dir_setup

            writer.write_as_json(
                new_bug_info,
                join(
                    list(self.task_mappings["fuzz"].keys())[0],
                    f"meta-data-{subtask_tag}.json",
                ),
            )

            self.do_step(
                new_bug_info,
                subtask_hash,
                subtask_tag,
                ["crash-analyze", "localize", "repair"],
            )
        except Exception as e:
            self.emit_warning(e)
            traceback.print_exc()
        pass

    def on_crash_analysis_finished(self, res):
        try:
            base_dir = list(self.task_mappings["crash-analyze"].keys())[0]
            benign_dir = join(base_dir, "benign_tests")
            crash_dir = join(base_dir, "crashing_tests")

            subtask_hash = hashlib.sha1()
            subtask_hash.update(str(time.time()).encode("utf-8"))
            subtask_tag = subtask_hash.hexdigest()[:8]

            (base_setup, enhanced_setup) = self.get_setup_directories(
                self.crash_analyze_root, subtask_tag
            )

            self.emit_debug(f"Setup dir is {base_setup}")
            self.emit_debug(f"New setup dir is {enhanced_setup}")

            shutil.copytree(base_setup, enhanced_setup)
            os.makedirs(join(enhanced_setup, "benign_tests"), exist_ok=True)
            os.makedirs(join(enhanced_setup, "crashing_tests"), exist_ok=True)

            self.copy_tests(crash_dir, enhanced_setup, "crashing_tests")
            self.copy_tests(benign_dir, enhanced_setup, "benign_tests")

            bug_info_extension = reader.read_json(join(base_dir, "meta-data.json"))

            new_bug_info = self.merge_dict(
                self.bug_info,
                (
                    bug_info_extension[0]
                    if isinstance(bug_info_extension, list)
                    else bug_info_extension
                ),
            )

            writer.write_as_json(
                new_bug_info,
                join(
                    list(self.task_mappings["crash-analyze"].keys())[0],
                    f"meta-data-{subtask_tag}.json",
                ),
            )

            self.do_step(
                new_bug_info, subtask_hash, subtask_tag, ["localize", "repair"]
            )
        except Exception as e:
            self.emit_warning(e)
            traceback.print_exc()
        pass

    def on_analysis_finished(self, event: FileSystemEvent):
        self.on_task_finished(event, ["fuzz", "localize", "repair"])

    def on_localization_finished(self, event: FileSystemEvent):
        self.on_task_finished(event, ["repair"])

    def on_repair_finished(self, event: FileSystemEvent):
        def copy_patches(
            base_setup: str, enhanced_setup: str, new_bug_info: Dict[str, Any]
        ):
            os.makedirs(join(enhanced_setup, "patches"), exist_ok=True)
            self.emit_debug(
                f"Copying patches from {dirname(event.src_path)} to {enhanced_setup}"
            )
            shutil.copytree(
                join(dirname(event.src_path), "patches"),
                join(enhanced_setup, "patches"),
                dirs_exist_ok=True,
            )
            # shutil.copy(event.src_path, join(enhanced_setup, "patches"))

        self.on_task_finished(event, ["validate"], copy_patches)

    def on_validation_finished(self, event: FileSystemEvent):
        self.emit_highlight("Validation finished")
        self.on_task_finished(event, ["select"])
        pass

    def on_selection_finished(self, event: FileSystemEvent):
        self.emit_highlight("Selection finished")
        self.emit_normal("The workflow has finished for this path.")
        pass

    def validate_metadata(self, metadata: List):
        validator = Draft7Validator(general_section_schema)
        errors = list(validator.iter_errors(metadata))
        if len(errors) != 0:
            for error in errors:
                self.emit_warning(error.message)
                self.emit_warning(error.path)
            raise ValueError("Metadata is not valid. Will not continue")

    def on_task_finished(
        self,
        event: FileSystemEvent,
        next_task_options: List[CompositeTaskType],
        on_copy: Optional[Callable[[str, str, Dict[str, Any]], None]] = None,
    ):
        """
        Generic method for handling the completion of a task.
        On_copy is an entrypoint for addditional processing that can be done after the copy of the setup directory.
        The arguments for on_copy are the base_setup, enhanced_setup directories and the new_bug_info.
        """
        try:
            subtask_hash = hashlib.sha1()
            subtask_hash.update(str(time.time()).encode("utf-8"))
            subtask_tag = subtask_hash.hexdigest()[:8]

            (base_setup, enhanced_setup) = self.get_setup_directories(
                self.localize_root, subtask_tag
            )

            self.emit_debug(f"Setup dir is {base_setup}")
            self.emit_debug(f"New setup dir is {enhanced_setup}")

            shutil.copytree(base_setup, enhanced_setup)

            bug_info_extension = reader.read_json(event.src_path)

            new_bug_info = self.merge_dict(
                self.bug_info,
                (
                    bug_info_extension[0]
                    if isinstance(bug_info_extension, list)
                    else bug_info_extension
                ),
            )

            if on_copy:
                on_copy(base_setup, enhanced_setup, new_bug_info)

            # self.validate_metadata([new_bug_info])

            self.do_step(new_bug_info, subtask_hash, subtask_tag, next_task_options)

        except Exception as e:
            self.stats.error_stats.is_error = True
            self.emit_warning(e)
            traceback.print_exc()
        pass

    def copy_tests(self, source_dir, destination_dir, subtype):
        os.makedirs(join(destination_dir, subtype, ""), exist_ok=True)
        for test_case in os.listdir(source_dir):
            if test_case == "README.txt":
                continue
            if os.path.isdir(join(source_dir, test_case)):
                # TODO directories are only copied over for now
                shutil.copytree(
                    join(source_dir, test_case),
                    join(destination_dir, subtype, test_case),
                    dirs_exist_ok=True,
                )
            else:
                shutil.copy(
                    join(source_dir, test_case),
                    join(destination_dir, subtype, ""),
                )

    def save_artifacts(self, dir_info):
        """
        Save useful artifacts from the repair execution
        output folder -> self.dir_output
        logs folder -> self.dir_logs
        The parent method should be invoked at last to archive the results
        """
        super().save_artifacts(dir_info)

    def analyse_output(self, dir_info, bug_id, fail_list):
        self.emit_normal("reading output")

        return self.stats

    def do_step(
        self,
        new_bug_info: Dict[str, Any],
        subtask_hash: Optional[Any],
        subtask_tag: Optional[str],
        next_task_options: List[CompositeTaskType],
    ):
        """
        Start subsequent tasks in the workflow.
        Next_task_options is assumed to be a sorted list of the tasks that can be executed.
        Returns False if no tool was available for any of the possible follow-up tasks.
        """
        callbacks = {
            "fuzz": self.on_fuzzing_finished,
            "crash-analyze": self.on_crash_analysis_finished,
        }
        for next_task in next_task_options:
            if next_task in self.tool_map:
                for tool, params, tag, type in self.tool_map[
                    cast(CompositeTaskType, next_task)
                ]:
                    self.pool.apply_async(
                        self.run_subtask,
                        [
                            type,
                            *self.get_args(
                                tool,
                                tag,
                                new_bug_info,
                                subtask_hash,
                                subtask_tag or tag,
                                params,
                                new_timeout=(
                                    None if next_task != "crash-analyze" else (2 / 60.0)
                                ),
                                real_task_type=next_task,
                            ),
                        ],
                        callback=callbacks.get(next_task, None),
                        error_callback=self.error_callback_handler,
                    )
                return True
        else:
            self.emit_warning(
                "Did not find a successor task from the options {}. Terminating this path.".format(
                    ",".join(next_task_options)
                )
            )
            return False

    def get_args(
        self,
        tool: AbstractTool,
        image_tag: str,
        new_bug_info: Optional[Dict[str, Any]] = None,
        new_hash: Optional[Any] = None,
        new_task_tag: Optional[str] = None,
        new_params: Optional[str] = None,
        new_timeout: Optional[float] = None,
        real_task_type: Optional[str] = None,
    ):
        """
        Construct the arguments for the run function from the proto_args.
        Certain arguments are replaceable.
        """
        (
            dir_info,
            benchmark,
            bug_info,
            composite_config_info,
            container_config_info,
            run_index,
            hash,
        ) = self.proto_args

        if new_bug_info:
            bug_info = new_bug_info

        if new_hash:
            hash = new_hash

        composite_config_info_new = deepcopy(composite_config_info)

        del composite_config_info_new["container-id"]

        if image_tag:
            composite_config_info_new[self.key_image_tag] = image_tag

        if new_task_tag:
            composite_config_info_new[self.key_task_tag] = new_task_tag

        if new_params:
            composite_config_info_new[definitions.KEY_TOOL_PARAMS] = new_params

        if new_timeout is not None:
            composite_config_info_new[self.key_timeout] = new_timeout

        if real_task_type:
            composite_config_info_new[self.key_real_type] = real_task_type

        return (
            dir_info,
            benchmark,
            bug_info,
            composite_config_info_new,
            container_config_info,
            run_index,
            hash,
            tool,
        )

    def get_setup_directories(self, root, subtask_tag):
        """
        Extracts the setup directories from the internal representation or the proto arguments.
        """
        if os.path.isfile(join(root, "cerberus_internal.json")):
            with open(join(root, "cerberus_internal.json"), "r") as f:
                data = json.loads(f.read())
                dir_info = data["dir_info"]
                # bug_info = data["bug_info"]
                base_setup = dir_info["local"]["setup"]
                previous_setup = basename(os.path.normpath(base_setup))
                if len(previous_setup.split("-")[-1]) == 8:
                    # The last argument is either the run index or the tool tag and for the run index to be reaching 8 digits, that is suspicious
                    enhanced_setup = join(
                        dirname(os.path.normpath(base_setup)),
                        f"{previous_setup[:-9]}-{subtask_tag}",
                    )
                else:
                    enhanced_setup = join(
                        dirname(os.path.normpath(base_setup)),
                        f"{previous_setup}-{subtask_tag}",
                    )
        else:
            dir_info = self.proto_args[0]
            base_setup = dir_info["local"]["setup"]
            enhanced_setup = join(
                dirname(os.path.normpath(base_setup)),
                f"{basename(os.path.normpath(base_setup))}-{subtask_tag}",
            )
        return (base_setup, enhanced_setup)

    def make_task_mappings(
        self, root_dir: str
    ) -> Dict[CompositeTaskType, Dict[str, Dict[str, str]]]:
        """
        Create the mappings for each task type.
        When the tool is created we add this mapping to allow for a common output directory
        """
        task_mappings: Dict[CompositeTaskType, Dict[str, Dict[str, str]]] = {
            "fuzz": {join(root_dir, "fuzzing"): {"bind": "/output", "mode": "rw"}},
            "repair": {join(root_dir, "repair"): {"bind": "/output", "mode": "rw"}},
            "analyze": {join(root_dir, "analyze"): {"bind": "/output", "mode": "rw"}},
            "select": {join(root_dir, "select"): {"bind": "/output", "mode": "rw"}},
            "validate": {join(root_dir, "validate"): {"bind": "/output", "mode": "rw"}},
            "localize": {join(root_dir, "localize"): {"bind": "/output", "mode": "rw"}},
            "crash-analyze": {
                join(root_dir, "crash-analyze"): {"bind": "/output", "mode": "rw"}
            },
        }

        self.repair_root = list(task_mappings["repair"].keys())[0]
        self.analyze_root = list(task_mappings["analyze"].keys())[0]
        self.fuzz_root = list(task_mappings["fuzz"].keys())[0]
        self.select_root = list(task_mappings["select"].keys())[0]
        self.validate_root = list(task_mappings["validate"].keys())[0]
        self.localize_root = list(task_mappings["localize"].keys())[0]
        self.crash_analyze_root = list(task_mappings["crash-analyze"].keys())[0]

        self.emit_debug(task_mappings)
        for task in task_mappings.values():
            for key in task.keys():
                os.makedirs(key, exist_ok=True)

        return task_mappings

    def event_worker(self):
        global active_jobs_lock  # Capture the process lock
        while True:
            event = self.message_queue.get()
            if isinstance(event, str):
                if event == self.exit_message:
                    if self.observer.is_alive():
                        self.observer.stop()
                    break
                elif event == self.exit_message_delayed:
                    time.sleep(60)  # wait for 60 seconds
                    with (
                        active_jobs_lock
                    ):  # If no task started in the past minute, exit
                        if self.active_jobs == 0:
                            self.message_queue.put(self.exit_message)
                else:
                    self.emit_debug(f"Got string {event}. Why?")

                continue
            if self.pre_process_event(event):
                # self.emit_debug("Got message {}".format(event))
                try:
                    self.process_event(event)
                except Exception as e:
                    print(f"Exception when processing {event}:\n {e}")

    def merge_dict(self, info, candidate):
        new_info = {}
        for key in info:
            new_info[key] = info[key]
            # Points of merging that are interesting are the keys
            if key in candidate and info[key] != candidate[key]:
                if type(info[key] != candidate[key]):
                    self.emit_warning(
                        "Overriding key {} with value {} with value {}".format(
                            key, info[key], candidate[key]
                        )
                    )
                    info[key] = candidate[key]
                else:
                    if type(info[key]) not in [list, dict]:
                        new_info[key] = candidate[key]
                    else:
                        if type(info[key]) == list:
                            new_info[key] = list(set(info[key] + candidate[key]))
                        elif type(info[key]) == dict:
                            new_info[key] = self.merge_dict(info[key], candidate[key])

        for key in candidate:
            if key not in info:
                new_info[key] = candidate[key]

        return new_info

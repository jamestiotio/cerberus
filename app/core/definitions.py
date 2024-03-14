KEY_BUG_ID = "bug_id"
KEY_BENCHMARK = "benchmark"
KEY_ID = "id"
KEY_SUBJECT = "subject"
KEY_LANGUAGE = "language"
KEY_FIX_FILE = "source_file"
KEY_FIX_FILE_LIST = "source_file_list"
KEY_REFERENCE_FILE = "reference_file"
KEY_FIX_LINES = "line_numbers"
KEY_FIX_LOC = "fix_loc"
KEY_PASSING_TEST = "passing_test"
KEY_FAILING_TEST = "failing_test"
KEY_CONFIG_TIMEOUT = "timeout"
KEY_TOOL_PARAMS = "params"
KEY_TOOL_TAG = "tag"
KEY_CONFIG_TIMEOUT_TESTCASE = "test_timeout"
KEY_CONFIG_FIX_LOC = "fault_location"
KEY_CONFIG_PATCH_DIR = "patch_directory"
KEY_CONFIG_TEST_RATIO = "passing_test_ratio"
KEY_BINARY_PATH = "binary_path"
KEY_COUNT_NEG = "count_neg"
KEY_COUNT_POS = "count_pos"
KEY_CRASH_CMD = "crash_input"
KEY_EXPLOIT_LIST = "exploit_file_list"
KEY_FUZZREPAIR_CRASH_CMD = "fuzzrepair_crash_input"
KEY_FUZZREPAIR_EXPLOIT_LIST = "fuzzrepair_exploit_file_list"
KEY_BUG_TYPE = "bug_type"
KEY_CLASS_DIRECTORY = "class_directory"
KEY_TEST_CLASS_DIRECTORY = "test_class_directory"
KEY_SOURCE_DIRECTORY = "source_directory"
KEY_TEST_DIRECTORY = "test_directory"
KEY_DEPENDENCIES = "dependencies"
KEY_COMMIT_BUGGY = "buggy_commit"
KEY_COMMIT_FIX = "fix_commit"
KEY_COMMIT_CHECKOUT = "checkout_commit"
KEY_TEST_TIMEOUT = "test_timeout"
KEY_SOURCE = "source"
KEY_SINK = "sink"
KEY_COMPILE_PROGRAMS = "compile_programs"
KEY_BUILD_COMMAND_PROJECT = "build_command_project"
KEY_BUILD_COMMAND_REPAIR = "build_command_repair"
KEY_BUILD_COMMAND = "build_command"
KEY_CLEAN_COMMAND = "clean_command"
KEY_CONFIG_COMMAND = "config_command"
KEY_BUILD_SCRIPT = "build_script"
KEY_CONFIG_SCRIPT = "config_script"
KEY_TEST_SCRIPT = "test_script"
KEY_PUB_TEST_SCRIPT = "pub_test_script"
KEY_PVT_TEST_SCRIPT = "pvt_test_script"
KEY_ADV_TEST_SCRIPT = "adv_test_script"
KEY_CONTAINER_CPU_COUNT = "cpu_count"
KEY_CONTAINER_GPU_COUNT = "gpu_count"
KEY_CONTAINER_MEM_LIMIT = "mem_limit"
KEY_CONTAINER_ENABLE_NETWORK = "enable_network"
KEY_ENABLED = "enabled"
KEY_GPUS = "gpus"
KEY_CPUS = "cpus"

KEY_JAVA_VERSION = "java_version"
KEY_BUILD_SYSTEM = "build_system"
KEY_COMPILE_CMD = "compile_cmd"
KEY_TEST_ALL_CMD = "test_all_cmd"
KEY_FAILING_MODULE_DIRECTORY = "failing_module"

ARG_ALL_CPU_COUNT = "--cpu-count"
ARG_ALL_GPU_COUNT = "--gpu-count"
ARG_TASK_CPU_COUNT = "--task-cpu-count"
ARG_USE_GPU = "--use-gpu"
ARG_CACHE = "--cache"
ARG_DATA_PATH = "--dir-data"
ARG_TOOL_PATH = "--tool-path"
ARG_TOOL_NAME = "--tool"
ARG_TOOL_LIST = "--tool-list"
ARG_SUBJECT_NAME = "--subject"
ARG_TOOL_PARAMS = "--tool-param"
ARG_TOOL_TAG = "--tool-tag"
ARG_DEBUG_MODE = "--debug"
ARG_BUG_INDEX = "--bug-index"
ARG_BUG_ID = "--bug-id"
ARG_START_INDEX = "--start-index"
ARG_END_INDEX = "--end-index"
ARG_SKIP_LIST = "--skip-index-list"
ARG_BUG_INDEX_LIST = "--bug-index-list"
ARG_BUG_ID_LIST = "--bug-id-list"
ARG_REBUILD_BASE_IMAGE = "--rebuild-base"
ARG_BENCHMARK = "--benchmark"
ARG_DOCKER_HOST = "--docker-host"
ARG_TASK_PROFILE_ID_LIST = "--task-profile-list"
ARG_CONTAINER_PROFILE_ID_LIST = "--container-profile-list"
ARG_CONFIG_FILE = "--config-file"
ARG_PARALLEL = "--parallel"
ARG_PURGE = "--purge"
ARG_RUNS = "--runs"
ARG_VALIDATOR_THREADS = "--vthread"
ARG_SHOW_DEV_PATCH = "--show-dev-patch"
ARG_USE_LOCAL = "--local"
ARG_USE_CONTAINER = "--container"
ARG_USE_LATEST_IMAGE = "--use-latest-image"
ARG_DUMP_PATCHES = "--dump"
ARG_VALKYRIE = "--valkyrie"
ARG_SETUP_ONLY = "--only-setup"
ARG_SKIP_SETUP = "--skip-setup"
ARG_ANALYSE_ONLY = "--only-analyse"
ARG_INSTRUMENT_ONLY = "--only-instrument"
ARG_RUN_TESTS_ONLY = "--only-test"
ARG_REBUILD_ALL_IMAGES = "--rebuild-all"
ARG_REBUILD_EXPERIMENT_IMAGE = "--rebuild-exp"
ARG_COMPACT_RESUTLS = "--compact-results"
ARG_TASK_TYPE = "--task-type"
ARG_SECURE_HASH = "--secure-hash"
ARG_SPECIAL_META = "--special-meta"

UI_TASK_PROFILE = "Task Profile"
UI_CONTAINER_PROFILE = "Container Profile"
UI_STARTED_AT = "Started at"
UI_SHOULD_FINISH = "Should finish by"
UI_STATUS = "Status"
UI_PLAUSIBLE_PATCHES = "Plausible Patches"
UI_DURATION = "Duration"

import datetime
import json
import os
import pathlib
import shutil

import obspython as obs

import psutil

__version__ = "1.0.1"


def script_description():
    return f"<b>Hjalles Recording Manager</b> v. {__version__}" + \
           "<hr>" + \
           "More features will come soon." + \
           "<hr>"


def script_load(settings):
    global SETTINGS

    SETTINGS = {}

    obs.obs_frontend_add_event_callback(on_event)

    output_path = obs.obs_frontend_get_current_record_output_path()
    obs.obs_data_set_default_string(settings, "RecordingOutDir", output_path)
    obs.obs_data_set_default_string(settings, "FilenameFormat", "%Y-%m-%d_%H-%M-%S")
    obs.obs_data_set_default_string(settings, "DateSortScheme", "%Y-%m-%d/")
    obs.obs_data_set_default_string(settings, "ExeSortList", ("bf4.exe, Battlefield 4, BF4\n"
                                                              "TslGame.exe, PUBG, PUBG\n"
                                                              "BF2042.exe, Battlefield 2042, BF2042\n"
                                                              "bfv.exe, Battlefield V, BF5"))


def script_update(settings):
    global SETTINGS, RECORDING_DIR, FILENAME_FORMAT, ENABLE_FILE_SORT, SORT_BY_DATE, DATE_SORT_SCHEME, FILE_SORT_BY, EXE_PREFIXES, EXE_LIST, FILE_OVERWRITE

    SETTINGS["RecordingOutDir"] = obs.obs_data_get_string(settings, "RecordingOutDir")
    SETTINGS["OverwriteExistingFile"] = obs.obs_data_get_bool(settings, "OverwriteExistingFile")

    SETTINGS["FilenameFormat"] = obs.obs_data_get_string(settings, "FilenameFormat")

    SETTINGS["SortRecordings"] = obs.obs_data_get_bool(settings, "SortRecordings")
    SETTINGS["SortByDate"] = obs.obs_data_get_bool(settings, "SortByDate")
    SETTINGS["DateSortScheme"] = obs.obs_data_get_string(settings, "DateSortScheme")
    SETTINGS["RecordingSortType"] = obs.obs_data_get_string(settings, "RecordingSortType")
    SETTINGS["ExeSortPrefixes"] = obs.obs_data_get_bool(settings, "ExeSortPrefixes")
    SETTINGS["ExeSortList"] = obs.obs_data_get_string(settings, "ExeSortList")


def file_sorting_modified(props, prop, settings, *args, **kwargs):
    value = obs.obs_data_get_string(settings, "RecordingSortType")
    exe_list = obs.obs_properties_get(props, "ExeSortList")
    exe_prefixes = obs.obs_properties_get(props, "ExeSortPrefixes")
    if value == "_sort_by_scene":
        obs.obs_property_set_visible(exe_list, False)
        obs.obs_property_set_visible(exe_prefixes, False)
    elif value == "_sort_by_exe":
        obs.obs_property_set_visible(exe_list, True)
        obs.obs_property_set_visible(exe_prefixes, True)

    return True  # VERY IMPORTANT


def script_properties():
    props = obs.obs_properties_create()

    recording_props = obs.obs_properties_create()
    recording_dir = obs.obs_properties_add_path(recording_props, "RecordingOutDir", "Recording output directory",
                                                obs.OBS_PATH_DIRECTORY, "", "")
    recording_menu = obs.obs_properties_add_group(props, "_recording_menu", "Recording settings", obs.OBS_GROUP_NORMAL,
                                                  recording_props)

    filename_props = obs.obs_properties_create()
    filename_format = obs.obs_properties_add_text(filename_props, "FilenameFormat", "Filename format",
                                                  type=obs.OBS_TEXT_DEFAULT)
    overwrite = obs.obs_properties_add_bool(filename_props, "OverwriteExistingFile", "Overwrite if file exists")
    filename_format_menu = obs.obs_properties_add_group(props, "_filename_format_menu",
                                                        "Filename formatting (recording only)",
                                                        obs.OBS_GROUP_NORMAL, filename_props)

    # ===== FILE SORTING OPTIONS =====
    file_sorting_props = obs.obs_properties_create()

    sort_by_date = obs.obs_properties_add_bool(file_sorting_props, "SortByDate", "Sort files by date")
    date_sort_scheme = obs.obs_properties_add_text(file_sorting_props, "DateSortScheme", "Date sorting scheme",
                                                   type=obs.OBS_TEXT_DEFAULT)
    obs.obs_property_set_enabled(date_sort_scheme, False)

    file_sort_by = obs.obs_properties_add_list(file_sorting_props, "RecordingSortType", "Categorize replays by",
                                               type=obs.OBS_COMBO_TYPE_LIST, format=obs.OBS_COMBO_FORMAT_STRING)
    obs.obs_property_set_modified_callback(file_sort_by, file_sorting_modified)
    obs.obs_property_list_add_string(file_sort_by, "Executable", "_sort_by_exe")
    obs.obs_property_list_add_string(file_sort_by, "Active scene", "_sort_by_scene")

    exe_prefixes = obs.obs_properties_add_bool(file_sorting_props, "ExeSortPrefixes",
                                               "Add per executable prefix to filename")
    exe_list = obs.obs_properties_add_text(file_sorting_props, "ExeSortList", "Executable list",
                                           type=obs.OBS_TEXT_MULTILINE)
    file_sorting_menu = obs.obs_properties_add_group(props, "SortRecordings", "Automatic file labeling and sorting",
                                                     obs.OBS_GROUP_CHECKABLE, file_sorting_props)

    return props


def getListOfProcessSortedByMemory():
    '''
    Get list of running process sorted by Memory Usage
    '''
    listOfProcObjects = []
    # Iterate over the list
    for proc in psutil.process_iter():
        try:
            # Fetch process details as dict
            pinfo = proc.as_dict(attrs=['pid', 'name', 'username'])
            pinfo['vms'] = proc.memory_info().vms / (1024 * 1024)
            # Append dict to list
            listOfProcObjects.append(pinfo);
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    # Sort list of dict by key vms i.e. memory usage
    listOfProcObjects = sorted(listOfProcObjects, key=lambda procObj: procObj['vms'], reverse=True)
    return listOfProcObjects


def find_exe_from_list():
    global EXE_LIST
    # Parse executable list into dict
    games = {}
    for game_list in [game.split(",") for game in EXE_LIST.strip().splitlines()]:
        games[game_list[0]] = {"name": game_list[1], "prefix": game_list[2]}
    for exe in getListOfProcessSortedByMemory():
        if exe["name"] in games:
            return games[exe["name"]]
    return None


def get_latest_recording_path():
    record_output = obs.obs_frontend_get_recording_output()
    data = obs.obs_output_get_settings(record_output)
    json_str = obs.obs_data_get_json(data)
    return json.loads(json_str)["path"]


def generate_filename(prefix="", suffix="", file_ext=""):
    global SETTINGS
    file_ext = file_ext.replace(".", "")
    filename = datetime.datetime.now().strftime(SETTINGS["FilenameFormat"])
    if prefix is not "":
        filename = f"{prefix}_{filename}"
    if suffix is not "":
        filename = f"{filename}_{suffix}"
    if file_ext is not "":
        filename = f"{filename}.{file_ext}"
    return filename


def save_recording(input_file, output_dir):
    global SETTINGS
    file_ext = input_file.suffix
    if len(input_file.name.split(".")[0]) == 0:  # Empty filename, e.g. ".mp4"
        file_ext = input_file.name.split(".")[1]
    prefix = ""
    if SETTINGS["ExeSortPrefixes"]:
        active_exe = find_exe_from_list()
        if active_exe is not None:
            prefix = active_exe["prefix"]
    new_filename = generate_filename(prefix=prefix, file_ext=file_ext)
    pathlib.Path(output_dir).mkdir(parents=True, exist_ok=True)
    new_path = os.path.join(output_dir, new_filename)
    if not SETTINGS["OverwriteExistingFile"]:
        num = 1
        while os.path.exists(new_path):
            filename = pathlib.Path(new_path).stem
            file_ext = pathlib.Path(new_path).suffix
            test_filename = f"{filename}_{num}{file_ext}"
            test_path = os.path.join(output_dir, test_filename)
            if not os.path.exists(test_path):
                new_path = test_path
                break
            num += 1
    shutil.move(input_file, new_path)


def generate_dir(root_dir):
    global SETTINGS
    return_dir = root_dir
    if SETTINGS["SortRecordings"]:
        if SETTINGS["RecordingSortType"] == "_sort_by_scene":
            current_scene = obs.obs_frontend_get_current_scene()
            name = obs.obs_source_get_name(current_scene)
            return_dir = os.path.join(return_dir, f"{name}/")
        elif SETTINGS["RecordingSortType"] == "_sort_by_exe":
            active_exe = find_exe_from_list()
            if active_exe is not None:
                name = active_exe["name"]
                return_dir = os.path.join(return_dir, name)
        if SETTINGS["SortByDate"]:
            date_path = datetime.datetime.now().strftime(SETTINGS["DateSortScheme"])
            return_dir = os.path.join(return_dir, date_path)
    return return_dir


def on_event(event):
    global SETTINGS
    if event == obs.OBS_FRONTEND_EVENT_RECORDING_STOPPED:
        recording_path = pathlib.Path(get_latest_recording_path())
        new_dir = generate_dir(SETTINGS["RecordingOutDir"])
        save_recording(recording_path, new_dir)

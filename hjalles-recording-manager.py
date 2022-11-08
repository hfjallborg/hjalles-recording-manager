import datetime
import glob
import json
import os
import pathlib
import shutil
import subprocess
import threading
import time

import obspython as obs
import psutil

__version__ = "1.2.0"

SETTINGS = None
SCRIPT_PROPERTIES = None
CURRENT_RECORDING = {
    "start_time": None,
    "time_splits": [],
    "total_size": 0,
    "total_time": 0
}


def script_description():
    return f"<b>Hjalles Recording Manager</b> v. {__version__}"


def script_load(settings):
    global SETTINGS

    SETTINGS = {}

    obs.obs_frontend_add_event_callback(on_event)

    output_path = obs.obs_frontend_get_current_record_output_path()
    obs.obs_data_set_default_string(settings, "RecordingOutDir", output_path)
    obs.obs_data_set_default_string(settings, "FilenameFormat", "%Y-%m-%d_%H-%M-%S")
    obs.obs_data_set_default_string(settings, "DatetimeSortScheme", "%Y-%m-%d/")
    obs.obs_data_set_default_string(settings, "ExeSortList", ("bf4.exe, Battlefield 4, BF4\n"
                                                              "TslGame.exe, PUBG, PUBG\n"
                                                              "BF2042.exe, Battlefield 2042, BF2042\n"
                                                              "bfv.exe, Battlefield V, BF5"))

    obs.obs_data_set_default_string(settings, "RemuxFilenameFormat", "%FILE%_remux")
    obs.obs_data_set_default_int(settings, "RemuxCRF", 23)
    obs.obs_data_set_default_string(settings, "RemuxH264Preset", "medium")

    obs.timer_add(split_file, 1000)


def script_update(settings):
    global SETTINGS, SCRIPT_PROPERTIES

    SCRIPT_PROPERTIES = settings

    SETTINGS["RecordingOutDir"] = obs.obs_data_get_string(settings, "RecordingOutDir")
    SETTINGS["OverwriteExistingFile"] = obs.obs_data_get_bool(settings, "OverwriteExistingFile")

    SETTINGS["FilenameFormat"] = obs.obs_data_get_string(settings, "FilenameFormat")

    SETTINGS["SortRecordings"] = obs.obs_data_get_bool(settings, "SortRecordings")
    SETTINGS["SortByDate"] = obs.obs_data_get_bool(settings, "SortByDate")
    SETTINGS["DatetimeSortScheme"] = obs.obs_data_get_string(settings, "DatetimeSortScheme")
    SETTINGS["RecordingSortType"] = obs.obs_data_get_string(settings, "RecordingSortType")
    SETTINGS["ExeSortPrefixes"] = obs.obs_data_get_bool(settings, "ExeSortPrefixes")
    SETTINGS["ExeSortList"] = obs.obs_data_get_string(settings, "ExeSortList")

    SETTINGS["EnableSplitRecording"] = obs.obs_data_get_bool(settings, "EnableSplitRecording")
    SETTINGS["SplitMaxSize"] = obs.obs_data_get_double(settings, "SplitMaxSize")
    SETTINGS["SplitMaxTime"] = obs.obs_data_get_double(settings, "SplitMaxTime")
    SETTINGS["SplitGatherFiles"] = obs.obs_data_get_bool(settings, "SplitGatherFiles")
    SETTINGS["SplitConcatenate"] = obs.obs_data_get_bool(settings, "SplitConcatenate")

    SETTINGS["RemuxRecordings"] = obs.obs_data_get_bool(settings, "RemuxRecordings")
    SETTINGS["RemuxMode"] = obs.obs_data_get_string(settings, "RemuxMode")
    SETTINGS["RemuxFilenameFormat"] = obs.obs_data_get_string(settings, "RemuxFilenameFormat")
    SETTINGS["RemuxVEncoder"] = obs.obs_data_get_string(settings, "RemuxVEncoder")
    SETTINGS["RemuxCRF"] = obs.obs_data_get_int(settings, "RemuxCRF")
    SETTINGS["RemuxFileContainer"] = obs.obs_data_get_string(settings, "RemuxFileContainer")
    SETTINGS["RemuxBitrate"] = obs.obs_data_get_int(settings, "RemuxBitrate")
    SETTINGS["RemuxBitrateMode"] = obs.obs_data_get_string(settings, "RemuxBitrateMode")
    SETTINGS["RemuxCustomFFmpeg"] = obs.obs_data_get_string(settings, "RemuxCustomFFmpeg")
    SETTINGS["RemuxH264Preset"] = obs.obs_data_get_string(settings, "RemuxH264Preset")
    SETTINGS["ManualRemuxMode"] = obs.obs_data_get_string(settings, "ManualRemuxMode")
    SETTINGS["ManualRemuxInputFile"] = obs.obs_data_get_string(settings, "ManualRemuxInputFile")
    SETTINGS["ManualRemuxInputFolder"] = obs.obs_data_get_string(settings, "ManualRemuxInputFolder")


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


def remux_settings_modified(props, prop, settings, *args, **kwargs):
    remux_file_format = obs.obs_properties_get(props, "RemuxFilenameFormat")
    if obs.obs_data_get_bool(settings, "RemuxReplaceOriginal"):
        obs.obs_property_set_enabled(remux_file_format, False)
    else:
        obs.obs_property_set_enabled(remux_file_format, True)

    # Get all UI elements for remux settings

    overwrite_b = obs.obs_properties_get(props, "RemuxReplaceOriginal")
    v_encoder_s = obs.obs_properties_get(props, "RemuxVEncoder")
    container_prop = obs.obs_properties_get(props, "RemuxFileContainer")
    br_slider = obs.obs_properties_get(props, "RemuxBitrate")
    crf_slider = obs.obs_properties_get(props, "RemuxCRF")
    preset_selector = obs.obs_properties_get(props, "RemuxH264Preset")
    filename_format = obs.obs_properties_get(props, "RemuxFilenameFormat")
    custom_ffmpeg = obs.obs_properties_get(props, "RemuxCustomFFmpeg")
    bitrate_mode = obs.obs_properties_get(props, "RemuxBitrateMode")

    remux_mode = obs.obs_data_get_string(settings, "RemuxMode")
    v_encoder = obs.obs_data_get_string(settings, "RemuxVEncoder")
    h264_preset = obs.obs_data_get_string(settings, "RemuxH264Preset")
    containers = []

    # Visble properties in standard mode
    std_props = [overwrite_b, v_encoder_s, container_prop, br_slider, crf_slider, preset_selector, filename_format,
                 bitrate_mode]
    # Visible properties in custom ffmpeg mode
    custom_props = [custom_ffmpeg, filename_format, overwrite_b]

    obs.obs_property_list_clear(container_prop)
    obs.obs_property_list_clear(preset_selector)
    if remux_mode == "standard":
        for p in custom_props:
            obs.obs_property_set_visible(p, False)
        for p in std_props:
            obs.obs_property_set_visible(p, True)

        if v_encoder == "copy":
            containers = [("mp4", "mp4 - MPEG-4"), ("mkv", "mkv - Matroska")]
            copy_props = [container_prop, v_encoder_s, filename_format, overwrite_b]
            for prop in copy_props:
                obs.obs_property_set_visible(prop, True)
            for prop in std_props:
                if prop not in copy_props:
                    obs.obs_property_set_visible(prop, False)

        elif v_encoder == "libx264":
            containers = [("mp4", "mp4 - MPEG-4"), ("mkv", "mkv - Matroska")]
            libx264_props = [overwrite_b, v_encoder_s, filename_format, container_prop, crf_slider, preset_selector]
            for p in libx264_props:
                obs.obs_property_set_visible(p, True)
            for p in std_props:
                if p not in libx264_props:
                    obs.obs_property_set_visible(p, False)
            for preset in ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower",
                           "veryslow", "placebo"]:
                obs.obs_property_list_add_string(preset_selector, preset, preset)

        elif v_encoder == "h264_nvenc":
            containers = [("mp4", "mp4 - MPEG-4"), ("mkv", "mkv - Matroska")]
            h264nvenc_props = [overwrite_b, v_encoder_s, filename_format, container_prop, br_slider, preset_selector]
            for p in h264nvenc_props:
                obs.obs_property_set_visible(p, True)
            for p in std_props:
                if p not in h264nvenc_props:
                    obs.obs_property_set_visible(p, False)
            for preset in [("default", 0), ("slow", 1), ("medium", 2), ("fast", 3), ("hp", 4), ("hq", 5), ("bd", 6),
                           ("ll", 7), ("llhq", 8), ("llhp", 9), ("lossless", 10), ("losslesshp", 11)]:
                obs.obs_property_list_add_string(preset_selector, preset[0], str(preset[1]))

        elif v_encoder == "libsvtav1":
            containers = [("mp4", "mp4 - MPEG-4"), ("mkv", "mkv - Matroska")]
            libaom_props = [overwrite_b, v_encoder_s, bitrate_mode, filename_format, container_prop]
            for p in libaom_props:
                obs.obs_property_set_visible(p, True)
            for p in std_props:
                if p not in libaom_props:
                    obs.obs_property_set_visible(p, False)

            obs.obs_property_list_clear(bitrate_mode)
            obs.obs_property_list_add_string(bitrate_mode, "Constant quality", "cq")
            br_mode = obs.obs_data_get_string(settings, "RemuxBitrateMode")
            if br_mode == "cq":
                obs.obs_property_set_visible(br_slider, False)
                obs.obs_property_set_visible(crf_slider, True)

        # elif v_encoder == "h264_amf":
        #     amf_props = [overwrite_b, v_encoder_s, filename_format, br_slider, container_prop]
        #     for prop in amf_props:
        #         obs.obs_property_set_visible(prop, True)
        #     for prop in std_props:
        #         if prop not in amf_props:
        #             obs.obs_property_set_visible(prop, False)
        #     containers = [("mp4", "mp4 - MPEG-4"), ("mkv", "mkv - Matroska")]
        for c in containers:
            obs.obs_property_list_add_string(container_prop, c[1], c[0])

    elif remux_mode == "custom_ffmpeg":
        for p in std_props:
            obs.obs_property_set_visible(p, False)
        for p in custom_props:
            obs.obs_property_set_visible(p, True)

    manual_remux_mode = obs.obs_data_get_string(settings, "ManualRemuxMode")
    manual_remux_file = obs.obs_properties_get(props, "ManualRemuxInputFile")
    manual_remux_folder = obs.obs_properties_get(props, "ManualRemuxInputFolder")
    if manual_remux_mode == "file":
        obs.obs_property_set_visible(manual_remux_file, True)
        obs.obs_property_set_visible(manual_remux_folder, False)
    elif manual_remux_mode == "batch":
        obs.obs_property_set_visible(manual_remux_file, False)
        obs.obs_property_set_visible(manual_remux_folder, True)

    return True


def generate_ffmpeg_cmd(input_path):
    global SETTINGS

    input_file = pathlib.Path(input_path)
    filename_format = SETTINGS["RemuxFilenameFormat"]
    stem = filename_format.replace("%FILE%", input_file.stem)
    container = SETTINGS["RemuxFileContainer"]
    output_filename = f"{stem}.{container}"
    output_path = os.path.join(input_file.parent, output_filename)

    if SETTINGS["RemuxMode"] == "standard":
        v_encoder = SETTINGS["RemuxVEncoder"]

        if v_encoder == "copy":
            ffmpeg_cmd = f"ffmpeg -i {input_path} -c:v copy -c:a copy -map 0 {output_path}"

        elif v_encoder == "libx264":
            crf = SETTINGS["RemuxCRF"]
            preset = SETTINGS["RemuxH264Preset"]
            ffmpeg_cmd = f"ffmpeg -i {input_path} -c:v {v_encoder} -preset 0 -crf {crf} -c:a copy -map 0 {output_path}"

        elif v_encoder == "h264_nvenc":
            cbr = SETTINGS["RemuxBitrate"]
            preset = SETTINGS["RemuxH264Preset"]
            ffmpeg_cmd = f"ffmpeg -i {input_path} -c:v h264_nvenc -preset {preset} -b:v {cbr}M -c:a copy -map 0 {output_path}"

        elif v_encoder == "libsvtav1":
            if SETTINGS["RemuxBitrateMode"] == "cq":
                cq = SETTINGS["RemuxCRF"]
                ffmpeg_cmd = f"ffmpeg -i {input_path} -c:v {v_encoder} -crf {cq} -b:v 0 -c:a copy -map 0 {output_path}"

        # elif v_encoder == "h264_amf":
        #     cbr = int(SETTINGS["RemuxBitrate"]) * 1000
    elif SETTINGS["RemuxMode"] == "custom_ffmpeg":
        ffmpeg_cmd = SETTINGS["RemuxCustomFFmpeg"].replace("%INPUT%", input_path).replace("%OUTPUT%", stem)

    return ffmpeg_cmd


def manual_remux(props, prop, *args, **kwargs):
    if SETTINGS["ManualRemuxMode"] == "file":
        ffmpeg_input = SETTINGS["ManualRemuxInputFile"]
        ffmpeg_cmd = generate_ffmpeg_cmd(ffmpeg_input)
        remux_thread = threading.Thread(target=run_ffmpeg, args=(ffmpeg_cmd,), daemon=True)
        remux_thread.start()
    elif SETTINGS["ManualRemuxMode"] == "batch":
        input_folder = SETTINGS["ManualRemuxInputFolder"]
        file_formats = ["mp4", "mkv"]
        input_files = []
        for ff in file_formats:
            input_files += glob.glob(f"{input_folder}/*.{ff}")
        remux_threads = []
        for file in input_files:
            ffmpeg_cmd = generate_ffmpeg_cmd(file)
            thread = threading.Thread(target=run_ffmpeg, args=(ffmpeg_cmd,))
            remux_threads.append(thread)
        for thread in remux_threads:
            thread.start()


def find_latest_file(directory, file_ext=[], exclude=[]):
    list_of_files = glob.glob(directory + "/*") + glob.glob(directory + "/.**")

    return_files = []
    for file in list_of_files:
        add = True
        if os.path.isdir(file):
            continue
        if len(file_ext) > 0:
            ext = file.split(".")[-1]
            if ext not in file_ext:
                add = False
                continue
        if len(exclude) > 0:
            for x in exclude:
                if os.path.abspath(x) == os.path.abspath(file):
                    add = False
                    continue

        if add:
            return_files.append(file)
    return sorted(return_files, key=lambda t: -os.stat(t).st_mtime)[0]


def split_file():
    global CURRENT_RECORDING

    if obs.obs_frontend_recording_active():
        if SETTINGS["EnableSplitRecording"]:
            max_size = SETTINGS["SplitMaxSize"]
            max_time = SETTINGS["SplitMaxTime"]
            output = obs.obs_frontend_get_recording_output()
            # Output file size in GB
            size = obs.obs_output_get_total_bytes(output) / (10**9) - CURRENT_RECORDING["total_size"]  # 1 GB = 10^9 bytes
            current_time = (datetime.datetime.now() - CURRENT_RECORDING["start_time"]).seconds // 60 - CURRENT_RECORDING["total_time"]

            if size >= max_size != 0:
                print("== Recording split (size)")
                total_size = CURRENT_RECORDING["total_size"] + size
                total_time = CURRENT_RECORDING["total_time"] + current_time
                CURRENT_RECORDING["total_size"] = total_size
                CURRENT_RECORDING["total_time"] = total_time
                obs.obs_frontend_recording_split_file()
                path = find_latest_file(obs.obs_frontend_get_current_record_output_path())
                CURRENT_RECORDING["time_splits"].append((path, datetime.datetime.now()))

            elif current_time >= max_time != 0:
                print("== Recording split (time)")
                total_size = CURRENT_RECORDING["total_size"] + size
                total_time = CURRENT_RECORDING["total_time"] + current_time
                CURRENT_RECORDING["total_size"] = total_size
                CURRENT_RECORDING["total_time"] = total_time
                obs.obs_frontend_recording_split_file()
                path = find_latest_file(obs.obs_frontend_get_current_record_output_path())
                CURRENT_RECORDING["time_splits"].append((path, datetime.datetime.now()))




def file_split_props(props):
    split_props = obs.obs_properties_create()

    obs.obs_properties_add_float_slider(split_props, "SplitMaxSize", "Max size (GB)", 0, 100, 0.1)
    obs.obs_properties_add_int_slider(split_props, "SplitMaxTime", "Max time (min)", 0, 120, 1)

    obs.obs_properties_add_bool(split_props, "SplitGatherFiles", "Gather split files in folder")
    obs.obs_properties_add_bool(split_props, "SplitConcatenate", "Concatenate split files")

    split_menu = obs.obs_properties_add_group(props, "EnableSplitRecording", "Automatic file splitting",
                                              obs.OBS_GROUP_CHECKABLE, split_props)

    return props


def file_sorting_properties(props):
    # ===== FILE SORTING OPTIONS =====
    file_sorting_props = obs.obs_properties_create()

    sort_by_date = obs.obs_properties_add_bool(file_sorting_props, "SortByDate", "Sort files by date")
    date_sort_scheme = obs.obs_properties_add_text(file_sorting_props, "DatetimeSortScheme", "Date sorting scheme",
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


def remux_properties(props):
    # ===== REMUXING OPTIONS =====
    auto_remux_props = obs.obs_properties_create()
    replace_orig = obs.obs_properties_add_bool(auto_remux_props, "RemuxReplaceOriginal", "Overwrite original file")
    remux_filename = obs.obs_properties_add_text(auto_remux_props, "RemuxFilenameFormat",
                                                 "Remuxed filename format",
                                                 type=obs.OBS_TEXT_DEFAULT)
    auto_remux_menu = obs.obs_properties_add_group(props, "RemuxRecordings", "Automatically remux recordings",
                                                   obs.OBS_GROUP_CHECKABLE, auto_remux_props)

    remux_props = obs.obs_properties_create()

    remux_mode = obs.obs_properties_add_list(remux_props, "RemuxMode", "Mode",
                                             type=obs.OBS_COMBO_TYPE_LIST, format=obs.OBS_COMBO_FORMAT_STRING)
    obs.obs_property_list_add_string(remux_mode, "Standard", "standard")
    obs.obs_property_list_add_string(remux_mode, "Custom FFmpeg", "custom_ffmpeg")
    obs.obs_property_set_modified_callback(remux_mode, remux_settings_modified)

    obs.obs_property_set_modified_callback(replace_orig, remux_settings_modified)
    v_encoder = obs.obs_properties_add_list(remux_props, "RemuxVEncoder", "Encoding",
                                            type=obs.OBS_COMBO_TYPE_LIST, format=obs.OBS_COMBO_FORMAT_STRING)
    obs.obs_property_set_modified_callback(v_encoder, remux_settings_modified)

    obs.obs_property_list_add_string(v_encoder, "Copy encoding", "copy")

    obs.obs_property_list_add_string(v_encoder, "H.264 (libx264)", "libx264")

    obs.obs_properties_add_list(remux_props, "RemuxBitrateMode", "Bitrate mode", type=obs.OBS_COMBO_TYPE_LIST,
                                format=obs.OBS_COMBO_FORMAT_STRING)

    crf_slider = obs.obs_properties_add_int_slider(remux_props, "RemuxCRF", "CRF/CQ", min=0, max=51, step=1)
    br_slider = obs.obs_properties_add_int_slider(remux_props, "RemuxBitrate", "CBR (mbps)", min=1, max=100, step=1)

    h264_preset = obs.obs_properties_add_list(remux_props, "RemuxH264Preset", "Preset", type=obs.OBS_COMBO_TYPE_LIST,
                                              format=obs.OBS_COMBO_FORMAT_STRING)

    obs.obs_property_list_add_string(v_encoder, "H.264 (Nvidia NVENC)", "h264_nvenc")

    obs.obs_property_list_add_string(v_encoder, "av1 (SVT-AV1)", "libsvtav1")

    # obs.obs_property_list_add_string(v_encoder, "H.264 (AMD AMF)", "h264_amf")

    container = obs.obs_properties_add_list(remux_props, "RemuxFileContainer", "File container",
                                            type=obs.OBS_COMBO_TYPE_LIST,
                                            format=obs.OBS_COMBO_FORMAT_STRING)

    custom_ffmpeg = obs.obs_properties_add_text(remux_props, "RemuxCustomFFmpeg", "Custom FFmpeg command",
                                                obs.OBS_TEXT_DEFAULT)

    remux_info = obs.obs_properties_add_text(remux_props, "RemuxInfo", "For information refer to the <a "
                                                                       "href='https://trac.ffmpeg.org/wiki'>FFmpeg "
                                                                       "wiki</a>.", type=obs.OBS_TEXT_INFO)

    remux_menu = obs.obs_properties_add_group(props, "RemuxMenu", "Remux settings",
                                              obs.OBS_GROUP_NORMAL, remux_props)

    # ===== Manual remuxing =====
    manual_remux_props = obs.obs_properties_create()
    manual_remux_mode = obs.obs_properties_add_list(manual_remux_props, "ManualRemuxMode", "Mode",
                                                    type=obs.OBS_COMBO_TYPE_LIST,
                                                    format=obs.OBS_COMBO_FORMAT_STRING)
    obs.obs_property_set_modified_callback(manual_remux_mode, remux_settings_modified)
    obs.obs_property_list_add_string(manual_remux_mode, "Single file", "file")
    obs.obs_property_list_add_string(manual_remux_mode, "Batch", "batch")

    obs.obs_properties_add_path(manual_remux_props, "ManualRemuxInputFile", "Input file", obs.OBS_PATH_FILE, "", "")
    obs.obs_properties_add_path(manual_remux_props, "ManualRemuxInputFolder", "Input folder", obs.OBS_PATH_DIRECTORY,
                                "",
                                SETTINGS["RecordingOutDir"])
    # obs.obs_properties_add_path(manual_remux_props, "ManualRemuxOutputFile", "Output file", obs.OBS_PATH_FILE_SAVE, "",
    #                             "")
    obs.obs_properties_add_button(manual_remux_props, "StartManualRemux", "Convert", manual_remux)

    manual_remux_menu = obs.obs_properties_add_group(props, "ManualRemuxMenu", "Manual remux",
                                                     obs.OBS_GROUP_NORMAL, manual_remux_props)

    return props


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

    props = file_sorting_properties(props)
    props = file_split_props(props)
    props = remux_properties(props)

    obs.obs_properties_apply_settings(props, SCRIPT_PROPERTIES)

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


def generate_filename(prefix="", suffix="", file_ext="", timestamp=None):
    global SETTINGS
    file_ext = file_ext.replace(".", "")
    if timestamp is None:
        timestamp = datetime.datetime.now()
    filename = timestamp.strftime(SETTINGS["FilenameFormat"])
    if prefix is not "":
        filename = f"{prefix}_{filename}"
    if suffix is not "":
        filename = f"{filename}_{suffix}"
    if file_ext is not "":
        filename = f"{filename}.{file_ext}"
    return filename


def save_recording(input_file, output_dir, timestamp=None, get_path_only=False):
    global SETTINGS
    file_ext = input_file.suffix
    if len(input_file.name.split(".")[0]) == 0:  # Empty filename, e.g. ".mp4"
        file_ext = input_file.name.split(".")[1]
    prefix = ""
    if SETTINGS["ExeSortPrefixes"]:
        active_exe = find_exe_from_list()
        if active_exe is not None:
            prefix = active_exe["prefix"]
    if timestamp is None:
        timestamp = datetime.datetime.now()
    new_filename = generate_filename(prefix=prefix, file_ext=file_ext, timestamp=timestamp)
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
    if not get_path_only:
        shutil.move(input_file, new_path)

    return new_path


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
            date_path = datetime.datetime.now().strftime(SETTINGS["DatetimeSortScheme"])
            return_dir = os.path.join(return_dir, date_path)
    return return_dir


def run_ffmpeg(ffmpeg_cmd):
    p = subprocess.run(ffmpeg_cmd, shell=True)
    return


def run_many_ffmpegs(ffmpeg_cmds):
    for cmd in ffmpeg_cmds:
        subprocess.run(cmd, shell=True)


def on_event(event):
    global SETTINGS, CURRENT_RECORDING

    if event == obs.OBS_FRONTEND_EVENT_RECORDING_STARTED:
        start_time = datetime.datetime.now()
        CURRENT_RECORDING = {
            "start_time": datetime.datetime.now(),
            "time_splits": [],
            "total_size": 0,
            "total_time": 0
        }
        print("===== RECORDING STARTED =====", f"\n{start_time}\n")

    elif event == obs.OBS_FRONTEND_EVENT_RECORDING_STOPPED:
        end_time = datetime.datetime.now()
        print("\n===== RECORDING STOPPED =====", f"\n{end_time}")

        if not SETTINGS["EnableSplitRecording"]:
            recording_path = pathlib.Path(get_latest_recording_path())
            new_dir = generate_dir(SETTINGS["RecordingOutDir"])
            output = save_recording(recording_path, new_dir)
            print(f"Saved recording -> {output}")

            if SETTINGS["RemuxRecordings"]:
                print("Remuxing recording...")
                ffmpeg_input = output
                ffmpeg_cmd = generate_ffmpeg_cmd(ffmpeg_input)
                remux_thread = threading.Thread(target=run_ffmpeg, args=(ffmpeg_cmd,))
                remux_thread.start()

        if SETTINGS["EnableSplitRecording"]:
            new_dir = generate_dir(SETTINGS["RecordingOutDir"])
            if SETTINGS["SplitGatherFiles"]:
                timestamp = end_time.strftime(SETTINGS["FilenameFormat"])
                split_dir = os.path.join(new_dir, timestamp)
                print(f"Gathering split files -> {split_dir}/")
            else:
                split_dir = new_dir
            path = find_latest_file(obs.obs_frontend_get_current_record_output_path())
            CURRENT_RECORDING["time_splits"].append((path, datetime.datetime.now()))
            concat_str = ""
            for split in CURRENT_RECORDING["time_splits"]:
                path = pathlib.Path(split[0])
                timestamp = split[1]
                output_path = save_recording(path, split_dir, timestamp=timestamp)
                concat_str += f"file '{output_path}'\n"

            if SETTINGS["SplitConcatenate"]:
                input_file = CURRENT_RECORDING["time_splits"][0][0]
                input_path = pathlib.Path(input_file)
                concat_path = save_recording(input_path, new_dir, timestamp=end_time,
                                             get_path_only=True)
                print(f"Concatenating split files -> {concat_path}")
                with open("concat.txt", "w") as f:
                    f.write(concat_str)

                if SETTINGS["RemuxRecordings"]:
                    print("Remuxing concatenated file...")
                    concat_cmd = f"ffmpeg -f concat -safe 0 -i concat.txt -c copy {concat_path}"
                    remux_cmd = generate_ffmpeg_cmd(concat_path)
                    ffmpeg_cmds = [concat_cmd, remux_cmd]
                    remux_thread = threading.Thread(target=run_many_ffmpegs, args=(ffmpeg_cmds,))
                    remux_thread.start()

                else:
                    ffmpeg_cmd = f"ffmpeg -f concat -safe 0 -i concat.txt -c copy {concat_path}"
                    remux_thread = threading.Thread(target=run_ffmpeg, args=(ffmpeg_cmd,))
                    remux_thread.start()




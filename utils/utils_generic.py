import json
import os
import pathlib
import shutil
import stat
import sys
import tarfile
import zipfile
import wget

import toml
from enum import Enum
from pathlib import Path
from utils.logger import get_logger
from typing import Any, List, Union, Optional, cast, IO, Dict


logger = get_logger(__name__)


class ISerializable:
    def to_dictionary(self) -> Dict[str, Any]:
        return self.__dict__


class Object(ISerializable):
    def __repr__(self):
        return str(self.__dict__)

    def to_dictionary(self):
        return dict(self.__dict__)

    def to_json(self):
        data_json = json.dumps(self.__dict__, indent=4)
        return data_json


class BasicEncoder(json.JSONEncoder):
    def default(self, o: Any):
        if isinstance(o, ISerializable):
            return o.to_dictionary()
        return json.JSONEncoder.default(self, o)


def split_to_chunks(items: Any, chunk_size: int):
    for i in range(0, len(items), chunk_size):
        yield items[i:i + chunk_size]


def omit_fields(data: Any, fields: List[str] = []):
    if isinstance(data, dict):
        for field in fields:
            data.pop(field, None)
        return data
    raise TypeError("omit_fields: only dictionaries are supported.")


def untar(archive_path: Path, destination_folder: Path) -> None:
    logger.debug(f"untar [{archive_path}] to [{destination_folder}].")

    ensure_folder(destination_folder)
    tar = tarfile.open(str(archive_path))
    tar.extractall(path=str(destination_folder))
    tar.close()

    logger.debug("untar done.")


def unzip(archive_path: Path, destination_folder: Path):
    logger.debug(f"unzip [{archive_path}] to [{destination_folder}].")

    ensure_folder(destination_folder)
    with zipfile.ZipFile(str(archive_path), "r") as my_zip:
        my_zip.extractall(str(destination_folder))

    logger.debug("unzip done.")


def ensure_folder(folder: Union[str, Path]):
    pathlib.Path(folder).mkdir(parents=True, exist_ok=True)


def uniquify(path: Path) -> Path:
    '''Generates the next available non-already-existing filename, by adding a _1, _2, _3, etc. suffix before the extension if necessary'''
    i = 1
    stem = path.stem
    while path.exists():
        path = path.with_stem(f"{stem}_{i}")
        i += 1
    return path


def download_file(url: str, destination_folder: Path = None) -> Path:
    if not destination_folder:
        destination_folder = Path.cwd() / 'downloads'
        
    ensure_folder(destination_folder)
    unique_destination = uniquify(destination_folder / Path(url).name)

    logger.debug(f"Downloading file from [{url}] to [{unique_destination}].")
    try:
        wget.download(url, str(unique_destination))
        print("")  # wget does not print newline
        return unique_destination
    except Exception as err:
        logger.error(f"Failed to download file from [{url}] with {err}. Closing process.")
        exit(1)
    

def get_file_from_url_or_path(url_or_path: Any) -> Path:
    if str(url_or_path).startswith("http"):
        return download_file(url_or_path)
    
    local_path = Path(url_or_path) if type(url_or_path) != Path else url_or_path
    if not local_path.exists():
        raise FileNotFoundError(f"File [{local_path}] not found!")
    return local_path


def read_lines(file: Path) -> List[str]:
    with open(file) as f:
        lines = f.readlines()
    lines = [line.strip() for line in lines]
    lines = [line for line in lines if line]
    return lines


# TODO delete this function, it is too generic
# TODO find usages in legolas
def read_file(f: Any, binary: bool = False) -> Union[str, bytes]:
    if isinstance(f, str) or isinstance(f, pathlib.PosixPath):
        path = Path(f)
        if binary:
            return read_binary_file(path)
        return read_text_file(path)

    file = cast(IO, f)
    result = file.read()
    assert isinstance(result, str) or isinstance(result, bytes)
    return result


def read_binary_file(path: Path) -> bytes:
    try:
        with open(path, 'rb') as binary_file:
            return binary_file.read()
    except Exception as err:
        raise OSError(str(path), err) from None


def read_text_file(path: Path) -> str:
    try:
        with open(path, 'r') as text_file:
            return text_file.read()
    except Exception as err:
        raise OSError(str(path), err) from None


def write_file(file_path: Path, text: str):
    with open(file_path, "w") as file:
        return file.write(text)


def read_toml_file(filename):
    return toml.load(str(filename))


def write_toml_file(filename, data):
    with open(str(filename), "w") as f:
        toml.dump(data, f)


def read_json_file(filename: Union[str, Path]) -> Any:
    with open(filename) as f:
        return json.load(f)


def write_json_file(filename: str, data: Any):
    with open(filename, "w") as f:
        json.dump(data, f, indent=4)


def dump_out_json(data: Any, outfile: Any = None):
    if not outfile:
        outfile = sys.stdout

    json.dump(data, outfile, indent=4, cls=BasicEncoder)
    outfile.write("\n")


def prettify_json_file(filename: str):
    data = read_json_file(filename)
    write_json_file(filename, data)


def get_subfolders(folder: Path) -> List[str]:
    return [item.name for item in os.scandir(folder) if item.is_dir() and not item.name.startswith(".")]


def mark_executable(file: str) -> None:
    logger.debug(f"Mark [{file}] as executable")
    st = os.stat(file)
    os.chmod(file, st.st_mode | stat.S_IEXEC)


def find_in_dictionary(dictionary, compound_path):
    keys = compound_path.split(".")
    node = dictionary
    for key in keys:
        node = node.get(key)
        if node is None:
            break

    return node


def list_files(folder: Path, suffix: Optional[str] = None) -> List[Path]:
    folder = folder.expanduser()
    files: List[Path] = [folder / file for file in os.listdir(folder)]
    files = [file for file in files if file.is_file()]

    if suffix:
        files = [file for file in files if str(file).lower().endswith(suffix.lower())]

    return files


def remove_folder(folder: Union[str, Path]):
    shutil.rmtree(folder, ignore_errors=True)


def symlink(real: str, link: str) -> None:
    if os.path.islink(link):
        os.remove(link)
    os.symlink(real, link)


def as_object(data: Object) -> Object:
    if isinstance(data, dict):
        result = Object()
        result.__dict__.update(data)
        return result

    return data


def is_arg_present(args: List[str], key: str) -> bool:
    for arg in args:
        if arg.find("--data") != -1:
            continue
        if arg.find(key) != -1:
            return True

    return False


def str_int_to_hex_str(number_str: str) -> str:
    num_of_bytes = 1
    if len(number_str) > 2:
        num_of_bytes = int(len(number_str) / 2)
    int_str = int(number_str)
    int_bytes = int_str.to_bytes(num_of_bytes, byteorder="big")
    bytes_str = int_bytes.hex()
    return bytes_str


def parse_keys(bls_public_keys):
    keys = bls_public_keys.split(',')
    parsed_keys = ''
    for key in keys:
        parsed_keys += '@' + key
    return parsed_keys, len(keys)


# https://code.visualstudio.com/docs/python/debugging
def breakpoint():
    import debugpy
    debugpy.listen(5678)
    print("Waiting for debugger attach")
    debugpy.wait_for_client()
    debugpy.breakpoint()


def get_continue_confirmation(force_continue: bool = False) -> bool:
    if force_continue:
        typed = "y"
    else:
        typed = input(f"Continue? y/n\n")

    while typed != "y" and typed != "n":
        typed = input(f"Wrong choice. Continue? y/n\n")

    if typed == "n":
        return False
    return True


class PrintColors(Enum):
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    PASS = '\033[92m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def print_color(msg, color: PrintColors):
    print(f"{color.value}{msg}{PrintColors.ENDC.value}")


def log_step_fail(msg):
    logger.error(msg)


def log_step_pass(msg):
    logger.info(msg)


def log_substep(msg):
    sub_step_print_header = " ├ "
    logger.info(f"{sub_step_print_header}{msg}")


def log_warning(msg):
    logger.warning(msg)


def log_unexpected_args(function_purpose: str, args: Any):
    logger.error(f"Failed to {function_purpose} due to unexpected number of arguments received!")
    logger.debug(f"Unexpected arguments: {args}")


def log_condition_assert(conditions: Dict[bool, str]):
    for condition, message in conditions.items():
        if condition:
            log_step_pass(f"PASS: {message}")
        else:
            log_step_fail(f"FAIL: {message}")


class TestStepCondition:
    def __init__(self, condition: bool, message: str):
        self.condition = condition
        self.message = message


class TestStepConditions:
    conditions: List[TestStepCondition]

    def __init__(self):
        self.conditions = []

    def add_condition(self, condition: bool, message: str):
        self.conditions.append(TestStepCondition(condition, message))

    def assert_conditions(self):
        for condition in self.conditions:
            if condition.condition:
                log_step_pass(f"PASS: {condition.message}")
            else:
                log_step_fail(f"FAIL: {condition.message}")

import json
import re
import sys


# Example of command:
# `python3 gen_pair_contract.py abis/pair.abi.json contracts/pair_contract_gen.py`


def abi_type_to_decoder_code(type: str):
  match = re.search(r"variadic<(.+)>", type)
  if match:
    return abi_type_to_decoder_code(match.group(1))
  match = re.search(r"Option<(.+)>", type)
  if match:
    inside_dec_code = abi_type_to_decoder_code(match.group(1))
    return f"d.Option({inside_dec_code})"
  match = re.search(r"tuple<(.+)>", type)
  if match:
    codes = [abi_type_to_decoder_code(t) for t in match.group(1).split(",")]
    code = ", ".join(codes)
    return f"d.Tuple([{code}])"
  if type == "bool":
    return "d.Bool()"
  if type == "u8":
    return "d.U8()"
  if type == "u16":
    return "d.U16()"
  if type == "u32":
    return "d.U32()"
  if type == "u64":
    return "d.U64()"
  if type == "BigUint":
    return "d.U()"
  if type == "Address":
    return "d.Addr()"
  if type == "TokenIdentifier":
    return "d.Str()"
  return f"{type}_decoder"


if len(sys.argv) < 3:
  raise ValueError("2 arguments must be provided: path to ABI and path to generated script.")

with open(sys.argv[1], "r") as file:
  data = json.load(file)

code = """from multiversx_sdk_core import Address

from utils.contract_interactor import ContractInteractor, Payment
from utils.decode import d


"""

contract_name = data["name"]

code += f"class {contract_name}ContractInteractor(ContractInteractor):\n"

for e_info in data["endpoints"]:
  e_name = e_info["name"]
  args_args_code = ""
  arg_codes = []
  for i_info in e_info["inputs"]:
    args_args_code += ", " + i_info["name"]
    i_type = i_info["type"]
    if i_type == "TokenIdentifier":
      args_args_code += ": str"
    elif i_type == "Address":
      args_args_code += ": Address"
    elif i_type == "BigUint":
      args_args_code += ": int"
    arg_codes.append(i_info["name"])
  args_call_code = ", ".join(arg_codes)
  if e_info["mutability"] == "readonly":
    decoder_codes = []
    for o_info in e_info["outputs"]:
      decoder_codes.append(abi_type_to_decoder_code(o_info["type"]))
    decoders_code = ", ".join(decoder_codes)
    code += f"\tdef query_{e_name}(self{args_args_code}):\n"
    code += f"\t\treturn self._query(\"{e_name}\", [{args_call_code}], [{decoders_code}])\n\n"
  elif e_info["mutability"] == "mutable":
    payment_args_code = ""
    payment_call_code = ""
    if "payableInTokens" in e_info:
      payment_args_code += ", _payment: Payment"
      payment_call_code += ", _payment"
    code += f"\tdef call_{e_name}(self{args_args_code}{payment_args_code}):\n"
    code += f"\t\treturn self._call(\"{e_name}\", [{args_call_code}], 0{payment_call_code})\n\n"
  else:
    raise ValueError("Unknown mutability.")

code += "\n"

for t_name, t_info in data["types"].items():
  if t_info["type"] == "struct":
    code += f"{t_name}_decoder = d.Tuple({{\n"
    for f_info in t_info["fields"]:
      f_name = f_info["name"]
      f_type = f_info["type"]
      code += f"\t\"{f_name}\": "
      code += abi_type_to_decoder_code(f_type)
      code += ",\n"
    code += "})\n\n"
  elif t_info["type"] == "enum":
    code += f"{t_name}_decoder = d.U8()\n\n"
  else:
    raise ValueError("Unknown type.")

with open(sys.argv[2], "w") as file:
  file.write(code)

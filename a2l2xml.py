import csv
import re
import uuid
import decimal

from os import path
from pya2l import DB, model
from pya2l.api import inspect
from sys import argv
from xml.etree.ElementTree import Element, SubElement, Comment, ElementTree
import xml.etree.ElementTree as ET

import pprint

USE_CONSTANTS = False  # Should we use "constants" / "scalars" in the XML? They kind of aren't good at all...

db = DB()
session = (
    db.open_existing(argv[1]) if path.exists(f"{argv[1]}db") else db.import_a2l(argv[1])
)

if argv[3] == "DQ250":
    BASE_OFFSET = 0x80000000
if argv[3] == "Simos18":
    BASE_OFFSET = (
        session.query(model.MemorySegment)
        .filter(model.MemorySegment.name == "_ROM")
        .first()
        .address
    )

data_sizes = {
    "UWORD": 2,
    "UBYTE": 1,
    "SBYTE": 1,
    "SWORD": 2,
    "ULONG": 4,
    "SLONG": 4,
    "FLOAT32_IEEE": 4,
}

storage_types = {
    "UBYTE": 'uint8',
    "SBYTE": 'int8',
    "UWORD": 'uint16',
    "SWORD": 'int16',
    "ULONG": 'uint32',
    "SLONG": 'int32',
    "FLOAT32_IEEE": 'float',
}

tables_in_xml = {
    "name": False,
    }

# XML Serialization methods

categories = []

# create a new context for this task
ctx = decimal.Context()
ctx.prec = 20

def xml_root_with_configuration(title):
    root = Element("ecus")

    xmlheader = SubElement(root, "ecu_struct")
    xmlheader.set('id',str(title).rstrip(".a2l").lstrip(".\\"))
    xmlheader.set('type',str(title).rstrip(".a2l").lstrip(".\\"))
    xmlheader.set('include',"")
    if argv[3] == "Simos18":
        xmlheader.set('desc_size',"#400000")
    if argv[3] == "DQ250":
        xmlheader.set('desc_size',"#140000")
    xmlheader.set('reverse_bytes',"False")
    xmlheader.set('ecu_type',"vag")
    xmlheader.set('flash_template',"")
    xmlheader.set('checksum',"")

    return [root, xmlheader]


def xml_table_with_root(root: Element, table_def):
    axis_count = 1
    if "x" in table_def:
        axis_count += 1
    if "y" in table_def:
        axis_count += 1
        
    table = SubElement(root, "map")
    table.set('name',table_def["title"])
    table.set("type",str(axis_count))
    table.set("help",table_def["description"])
    table.set("class","|".join(table_def["category"]))

    data = SubElement(table,"data")
    data.set("offset","#"+table_def['z']['address'].lstrip("0x"))
    data.set("storagetype",str(storage_types[table_def['z']["dataSize"]]))
    data.set("func_2val",table_def['z']['math'])
    data.set("func_val2",table_def['z']['math2'])
    data.set("format","%0.2f")
    data.set("metric",table_def['z']['units'])
    data.set("min",str(table_def['z']['min']))
    data.set("max",str(table_def['z']['max']))
    if argv[3] == "Simos18":
        data.set("order", "rc")

    if "x" in table_def:
        rows = SubElement(table,"cols")
        rows.set("count",str(table_def['x']['length']))
        rows.set("offset","#"+table_def['x']['address'].lstrip("0x"))
        rows.set("storagetype",str(storage_types[table_def['x']["dataSize"]]))
        rows.set("func_2val",table_def['x']['math'])
        rows.set("func_val2",table_def['x']['math2'])
        rows.set("format","%0.2f")
        rows.set("metric",table_def['x']['units'])
        if table_def['x']['conv_typ'] == "TAB_VERB":
            for values in table_def['x']['values']:
                valueElement = SubElement(rows, "value")
                valueElement.text = values


    if "y" in table_def:
        cols = SubElement(table,"rows")
        cols.set("count",str(table_def['y']['length']))
        cols.set("offset","#"+table_def['y']['address'].lstrip("0x"))
        cols.set("storagetype",str(storage_types[table_def['y']["dataSize"]]))
        cols.set("func_2val",table_def['y']['math'])
        cols.set("func_val2",table_def['y']['math2'])
        cols.set("format","%0.2f")
        cols.set("metric",table_def['y']['units'])
        if table_def['y']['conv_typ'] == "TAB_VERB":
            for values in table_def['y']['values']:
                valueElement = SubElement(cols, "value")
                valueElement.text = values

    return table


def calc_map_size(characteristic: inspect.Characteristic):
    data_size = data_sizes[characteristic.deposit.fncValues["datatype"]]
    map_size = data_size
    for axis_ref in characteristic.axisDescriptions:
        map_size *= axis_ref.maxAxisPoints
    return map_size


def adjust_address(address):
    return address - BASE_OFFSET + int(argv[4], base=16)


# A2L to "normal" conversion methods


def fix_degree(bad_string):
    return re.sub(
        "\uFFFD", "\u00B0", bad_string
    )  # Replace Unicode "unknown" with degree sign


def axis_ref_to_dict(axis_ref: inspect.AxisDescr):
    axis_value = {
        "name": axis_ref.axisPtsRef.name,
        "units": fix_degree(axis_ref.axisPtsRef.compuMethod.unit),
        "min": axis_ref.lowerLimit,
        "max": axis_ref.upperLimit,
        "address": hex(
            adjust_address(axis_ref.axisPtsRef.address)
            #+ data_sizes[axis_ref.axisPtsRef.depositAttr.axisPts["x"]["datatype"]]
        ),  # We need to offset the axis by 1 value, the first value is another length
        "length": axis_ref.maxAxisPoints,
        "dataSize": axis_ref.axisPtsRef.depositAttr.axisPts["x"]["datatype"],
        "conv_typ": axis_ref.compuMethod.conversionType,
    }
    
    if argv[3] == "Simos18":
        axis_value["address"] = hex(
            adjust_address(axis_ref.axisPtsRef.address)
            + data_sizes[axis_ref.axisPtsRef.depositAttr.axisPts["x"]["datatype"]]
        )
    
    if axis_ref.compuMethod.conversionType == "TAB_VERB":
        axis_value["values"] = axis_ref.compuMethod.tab_verb["text_values"]
        
    if len(axis_ref.compuMethod.coeffs) > 0:
        axis_value["math"] = coefficients_to_equation(axis_ref.compuMethod.coeffs, False)
    else:
        axis_value["math"] = "X"

    if len(axis_ref.compuMethod.coeffs) > 0:
        axis_value["math2"] = coefficients_to_equation(axis_ref.compuMethod.coeffs, True)
    else:
        axis_value["math2"] = "X"
        
    return axis_value

def axis_ref_to_dict_fix(axis_ref: inspect.AxisDescr, c_data):
    axis_value = {
        "name": axis_ref.inputQuantity,
        "units": fix_degree(axis_ref.compuMethod.unit),
        "min": axis_ref.lowerLimit,
        "max": axis_ref.upperLimit,
        "address": hex(0),
        "length": axis_ref.maxAxisPoints,
        "dataSize": "UBYTE",
        "conv_typ": axis_ref.compuMethod.conversionType,
    }

    if axis_ref.compuMethod.conversionType == "TAB_VERB":
        axis_value["values"] = axis_ref.compuMethod.tab_verb["text_values"]
    
    if len(axis_ref.compuMethod.coeffs) > 0:
        axis_value["math"] = coefficients_to_equation(axis_ref.compuMethod.coeffs, False)
    else:
        axis_value["math"] = "X"

    if len(axis_ref.compuMethod.coeffs) > 0:
        axis_value["math2"] = coefficients_to_equation(axis_ref.compuMethod.coeffs, True)
    else:
        axis_value["math2"] = "X"
        
    return axis_value

def axis_ref_to_dict_std_0(axis_ref: inspect.AxisDescr, c_data):
    axis_value = {
        "name": axis_ref.inputQuantity,
        "units": fix_degree(axis_ref.compuMethod.unit),
        "min": axis_ref.lowerLimit,
        "max": axis_ref.upperLimit,
        "address": hex(
            adjust_address(c_data.address)
            + data_sizes[c_data.deposit.axisPts["x"]["datatype"]]
        ),
        "length": axis_ref.maxAxisPoints,
        "dataSize": c_data.deposit.axisPts["x"]["datatype"],
        "conv_typ": axis_ref.compuMethod.conversionType,
    }
    
    if axis_ref.compuMethod.conversionType == "TAB_VERB":
        axis_value["values"] = axis_ref.compuMethod.tab_verb["text_values"]
    
    if len(axis_ref.compuMethod.coeffs) > 0:
        axis_value["math"] = coefficients_to_equation(axis_ref.compuMethod.coeffs, False)
    else:
        axis_value["math"] = "X"

    if len(axis_ref.compuMethod.coeffs) > 0:
        axis_value["math2"] = coefficients_to_equation(axis_ref.compuMethod.coeffs, True)
    else:
        axis_value["math2"] = "X"
        
    return axis_value


def axis_ref_to_dict_std_1(axis_ref: inspect.AxisDescr, c_data):
    axis_value = {
        "name": axis_ref.inputQuantity,
        "units": fix_degree(axis_ref.compuMethod.unit),
        "min": axis_ref.lowerLimit,
        "max": axis_ref.upperLimit,
        "address": hex(
            adjust_address(c_data.address)
            + data_sizes[c_data.deposit.axisPts["x"]["datatype"]]
            + c_data.deposit.axisPts["x"]["memSize"]
            + data_sizes[c_data.deposit.axisPts["y"]["datatype"]]
        ),
        "length": axis_ref.maxAxisPoints,
        "dataSize": c_data.deposit.axisPts["y"]["datatype"],
        "conv_typ": axis_ref.compuMethod.conversionType,
    }
    
    if axis_ref.compuMethod.conversionType == "TAB_VERB":
        axis_value["values"] = axis_ref.compuMethod.tab_verb["text_values"]
    
    if len(axis_ref.compuMethod.coeffs) > 0:
        axis_value["math"] = coefficients_to_equation(axis_ref.compuMethod.coeffs, False)
    else:
        axis_value["math"] = "X"

    if len(axis_ref.compuMethod.coeffs) > 0:
        axis_value["math2"] = coefficients_to_equation(axis_ref.compuMethod.coeffs, True)
    else:
        axis_value["math2"] = "X"
        
    return axis_value


def coefficients_to_equation(coefficients, inverse):
    a, b, c, d, e, f = (
        float_to_str(coefficients["a"]),
        float_to_str(coefficients["b"]),
        float_to_str(coefficients["c"]),
        float_to_str(coefficients["d"]),
        float_to_str(coefficients["e"]),
        float_to_str(coefficients["f"]),
    )

    s1 = '+'
    s2 = '-'
    if c[0] == '-':
        c = c[1:]
        s1 = '-'
        s2 = '+'
        
    operation = ""
    if inverse is True:
        operation = f"({b} * ([x] / {f})) {s1} {c}"
    else:  
        operation = f"(({f} * [x]) {s2} {c}) / {b}"
        
    if a == "0.0" and d == "0.0" and e=="0.0" and f!="0.0":  # Polynomial is of order 1, ie linear original: f"(({f} * [x]) - {c} ) / ({b} - ({e} * [x]))"
        return operation
    else:
        return "Cannot handle polynomial ratfunc because we do not know how to invert!"


def float_to_str(f):
    """
    Convert the given float to a string,
    without resorting to scientific notation
    """
    d1 = ctx.create_decimal(repr(f))
    return format(d1, 'f')

# Begin

root, xmlheader = xml_root_with_configuration(argv[1])


def build_table(characteristic, tablename, category, category2, category3, custom_name):
    if characteristic is None:
        print("******** Could not find ! ", tablename)
        return
    #print('characteristic type: ' + axis_pt_check)
    if str(type(characteristic)) == "<class 'pya2l.api.inspect.AxisPts'>":
        print("******** Skipping Axis Pt Table ! ", tablename)
        return
    print("Table: ", tablename)
    c_data = inspect.Characteristic(session, tablename)
    #print("c_data: ", c_data)
    table_offset = adjust_address(c_data.address)
    table_length = calc_map_size(c_data)
    axisDescriptions = c_data.axisDescriptions

    table_def = {
        "title": c_data.longIdentifier,
        "category": [category],
        "z": {
            "min": c_data.lowerLimit,
            "max": c_data.upperLimit,
            "address": hex(adjust_address(c_data.address)),
            "dataSize": c_data.deposit.fncValues["datatype"],
        },
    }

    if argv[3] == "DQ250":
        table_def["description"] = c_data.name
    else:
        table_def["description"] = c_data.displayIdentifier

    if c_data.compuMethod == "NO_COMPU_METHOD":
        table_def["z"]["units"] = ""
    else:
        table_def["z"]["units"] = fix_degree(c_data.compuMethod.unit)

    if custom_name is not None and len(custom_name) > 0:
        # table_def["description"] += f'|Original Name: {table_def["title"]}'
        table_def["title"] = custom_name

    id_name = table_def["description"]
    table_def["title"] += f" ({id_name})"
    

    if category2 is not None and len(category2) > 0:
        table_def["category"].append(category2)
        
    if category3 is not None and len(category3) > 0:
        table_def["category"].append(category3)

    if c_data.compuMethod == "NO_COMPU_METHOD":
        table_def["z"]["math"] = "X"
    elif len(c_data.compuMethod.coeffs) > 0:
        table_def["z"]["math"] = coefficients_to_equation(c_data.compuMethod.coeffs, False)
    else:
        table_def["z"]["math"] = "X"

    if c_data.compuMethod == "NO_COMPU_METHOD":
        table_def["z"]["math2"] = "X"
    elif len(c_data.compuMethod.coeffs) > 0:
        table_def["z"]["math2"] = coefficients_to_equation(c_data.compuMethod.coeffs, True)
    else:
        table_def["z"]["math2"] = "X"

    if len(axisDescriptions) == 0 and USE_CONSTANTS is True:
        table_def["constant"] = True
    
    if len(axisDescriptions) > 0 and hasattr(axisDescriptions[0].axisPtsRef, 'address'):
        table_def["x"] = axis_ref_to_dict(axisDescriptions[0])
        table_def["z"]["length"] = table_def["x"]["length"]
        table_def["description"] += f'|X: {table_def["x"]["name"]}'
    
    if len(axisDescriptions) > 1 and hasattr(axisDescriptions[1].axisPtsRef, 'address'):
        table_def["y"] = axis_ref_to_dict(axisDescriptions[1])
        table_def["z"]["rows"] = table_def["y"]["length"]
        table_def["description"] += f'|Y: {table_def["y"]["name"]}'

    if len(axisDescriptions) > 0 and axisDescriptions[0].attribute == "FIX_AXIS":
        table_def["x"] = axis_ref_to_dict_fix(axisDescriptions[0], c_data)
        table_def["z"]["length"] = table_def["x"]["length"]
        table_def["description"] += f'\nX: {table_def["x"]["name"]}'
        
    if len(axisDescriptions) > 1 and axisDescriptions[1].attribute == "FIX_AXIS":
        table_def["y"] = axis_ref_to_dict_fix(axisDescriptions[1], c_data)
        table_def["z"]["rows"] = table_def["y"]["length"]
        table_def["description"] += f'\nY: {table_def["y"]["name"]}'
        
    if len(axisDescriptions) > 0 and axisDescriptions[0].attribute == "STD_AXIS":
        table_def["z"]["address"] = hex(
                                adjust_address(c_data.address)
                                + data_sizes[c_data.deposit.axisPts["x"]["datatype"]]
                                + c_data.deposit.axisPts["x"]["memSize"])
        table_def["x"] = axis_ref_to_dict_std_0(axisDescriptions[0], c_data)
        table_def["z"]["length"] = table_def["x"]["length"]
        table_def["description"] += f'\nX: {table_def["x"]["name"]}'

    if len(axisDescriptions) > 1 and axisDescriptions[1].attribute == "STD_AXIS":
        table_def["z"]["address"] = hex(
                                adjust_address(c_data.address)
                                + data_sizes[c_data.deposit.axisPts["x"]["datatype"]]
                                + c_data.deposit.axisPts["x"]["memSize"]
                                + data_sizes[c_data.deposit.axisPts["y"]["datatype"]]
                                + c_data.deposit.axisPts["y"]["memSize"])
        table_def["y"] = axis_ref_to_dict_std_1(axisDescriptions[1], c_data)
        table_def["z"]["rows"] = table_def["y"]["length"]
        table_def["description"] += f'\nY: {table_def["y"]["name"]}'

    table = xml_table_with_root(xmlheader, table_def)
 
 
if argv[2] == "ALL":
    if argv[3] == "Simos18":    
        for func in session.query(model.Function).order_by(model.Function.name).all():
            chars = inspect.Function(session, func.name).defCharacteristics
            for char in chars:
                build_table(char, char.name, func.name, "", "", "")
                
    if argv[3] == "DQ250":
        for group in session.query(model.Group).order_by(model.Group.groupName).all():
            chars = inspect.Group(session, group.groupName)
            charss = chars.characteristics
            for char in charss:
                build_table(char, char.name, group.groupName, "", "", "")

else:
    with open(argv[2], encoding="utf-8-sig") as csvfile:
        csvreader = csv.DictReader(csvfile)
        for row in csvreader:
            characteristic = (
                    session.query(model.Characteristic)
                    .order_by(model.Characteristic.name)
                    .filter(model.Characteristic.name == row["Table Name"])
                    .first()
            )
            build_table(characteristic, row["Table Name"], row["Category 1"], row["Category 2"], row["Category 3"], row["Custom Name"])

tree = ET.ElementTree(root)
ET.indent(tree, space="\t", level=0)
tree.write(f"{argv[1].strip('.a2l')}.{argv[2].strip('.csv')}.xml")
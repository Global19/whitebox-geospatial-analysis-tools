
import os
import shutil
import struct

import numpy as np
import xarray as xr

INPUT_ARGS = ['input', 'inputs', 'i', 'pour_pts', 'd8_pntr']
OUTPUT_ARGS = ['output', 'outputs', 'o']
WHITEBOX_TEMP_DIR = os.environ.get('WHITEBOX_TEMP_DIR')
if not WHITEBOX_TEMP_DIR:
    WHITEBOX_TEMP_DIR = os.path.expanduser('~/.whitebox_tools_tempdir')
    if not os.path.exists(WHITEBOX_TEMP_DIR):
        os.mkdir(WHITEBOX_TEMP_DIR)
if not os.path.exists(WHITEBOX_TEMP_DIR):
    raise ValueError('{} does not exist - Define environment variable: WHITEBOX_TEMP_DIR'.format(WHITEBOX_TEMP_DIR))

try:
    strings = (str, unicode)
except:
    strings = (str,)

DEP_TEMPLATE = '''Min:  {min}
Max:    {max}
North:  {north}
South:  {south}
East:   {east}
West:   {west}
Cols:   {cols}
Rows:   {rows}
Stacks: {stacks}
Data Type:  {dtype}
Z Units:    {z_units}
Xy Units:   {xy_units}
Projection: {projection}
Data Scale: {data_scale}
Display Min:    {display_min}
Display Max:    {display_max}
Preferred Palette:  {preferred_palette}
Palette Nonlinearity: {palette_nonlinearity}
Nodata: {nodata}
Byte Order: {byte_order}
{metadata_entry}'''

DEP_KEYS = [x.split(':')[0].strip() for x in DEP_TEMPLATE.splitlines()
            if ':' in x]

DTYPES = {'float': 'f4',
          'integer': 'i2'}
ENDIAN = {'LITTLE_ENDIAN': '<',
          'BIG_ENDIAN': '>',}

OK_DATA_SCALES = ['continuous', 'categorical', 'Boolean', 'rgb']

OPTIONAL_DEP_FIELDS = ['display_min', 'display_max',
                       'metadata_entry', 'projection',
                       'preferred_palette',
                       'palette_nonlinearity', 'byte_order', 'nodata']
REQUIRED_DEP_FIELDS = ['max', 'min', 'north', 'south', 'east', 'west',
                       'cols', 'rows', 'dtype', 'z_units', 'xy_units',
                       'data_scale']
FLOAT_DEP_FIELDS = ['Min', 'Max',
                    'North', 'South', 'East', 'West',
                    'Display Min', 'Display Max']
INT_DEP_FIELDS = ['Cols', 'Rows', 'Stacks']
UPPER_STR_FIELDS = ['Data Type', 'Byte Order']
def not_2d_error():
    raise NotImplementedError('Only 2-D rasters are supported by xarray wrapper currently')


def _lower_key(k):
    return '_'.join(k.lower().split())


def _assign_nodata(arr, no_data):
    if 'int' in arr.dtype.name:
        arr.values = arr.values.astype(np.float64)
    arr.values[arr.values == no_data] = np.NaN
    return arr


def assign_nodata(dset_or_arr, **dep):
    no_data = dep.get('Nodata', None)
    if no_data is None:
        return dset_or_arr
    if isinstance(dset_or_arr, xr.Dataset):
        for k, v in dset_or_arr.data_vars.items():
            _assign_nodata(v, no_data)
    else:
        _assign_nodata(dset_or_arr, no_data)
    return dset_or_arr



def case_insensitive_attrs(attrs, typ):
    lower = {'dtype': typ}
    for k, v in attrs.items():
        lower[_lower_key(k)] = v
    if 'xy_units' not in lower and 'units' in lower:
        lower['xy_units'] = lower['units']
    if 'z_units' not in lower and 'units' in lower:
        lower['z_units'] = lower['units']
    if not 'preferred_palette' in lower:
        lower['palette_nonlinearity'] = 'high_relief.pal'
    if not 'palette_nonlinearity' in lower:
        lower['palette_nonlinearity'] = 1.
    #lower['metadata_entry'] =  lower.get('metadata_entry', '').splitlines():
    has_keys = set(lower)
    needs_keys = set(REQUIRED_DEP_FIELDS)
    if not has_keys >= needs_keys:
        missing = needs_keys - has_keys
        raise ValueError('Did not find the following keys in DataArray: {} (found {})'.format(missing, lower))
    for k in OPTIONAL_DEP_FIELDS:
        if k not in lower:
            lower[k] = ''
    data_scale = (lower.get('data_scale') or '').lower()
    if not data_scale in OK_DATA_SCALES:
        raise ValueError('Data Scale (data_scale) is not in {} - attrs: {}'.format(OK_DATA_SCALES, lower))
    if data_scale == 'rgb':
        raise NotImplementedError('RGB DataArrays are not handled yet - serialize first, then run command line WhiteBox tool')
    return lower


def fix_path(path):
    paths = path.split(', ')
    paths = [os.path.abspath(os.path.join(os.curdir, path))
             for path in paths]
    if len(paths) == 1:
        return paths[0]
    return ', '.join(paths)


def to_tas(vals, typ_str, fname):
    if vals.ndim != 2:
        not_2d_error()
    r, c = vals.shape
    if typ_str == 'integer':
        abbrev = 'h'
    else:
        abbrev = 'f'
    with open(fname, 'wb') as f:
        for i in range(r):
            f.write(struct.pack(abbrev * c, *vals[i, :]))


def _from_dep(fname):
    with open(fname) as f:
        content = f.read()
    attrs = {}
    for line in content.splitlines():
        parts = line.strip().split(':')
        key, value = parts[0], ':'.join(parts[1:]).strip()
        key = key.strip().title()
        if key in INT_DEP_FIELDS:
            value = int(value)
        elif key in FLOAT_DEP_FIELDS:
            value = float(value)
        elif key not in UPPER_STR_FIELDS:
            value = value.upper()
        if key == 'Metadata Entry':
            if not key in attrs:
                attrs[key] = value
            else:
                attrs[key] += '\n' + value
        else:
            attrs[key] = value
    return attrs


def _get_dtype(dtype_str):
    if 'float' in dtype_str.lower():
        return ('float', DTYPES['float'])
    else:
        return ('integer', DTYPES['integer'])


def from_dep(dep, tas=None):
    if not dep or not os.path.exists(dep):
        raise ValueError('File {} does not exist'.format(dep))
    if not tas and dep.endswith('.dep'):
        tas = dep[:-4] + '.tas'
    if not tas or not os.path.exists(tas):
        raise ValueError('Expected .tas file at {} (guessed from {})'.format(tas, dep))
    attrs = _from_dep(dep)
    _, dtype = _get_dtype(attrs.get('Data Type'))
    byte_order = attrs.get('byte_order')
    if byte_order in ENDIAN:
        dtype = ENDIAN[byte_order] + dtype
    val = np.fromfile(tas, dtype=dtype)
    val.resize(attrs['Rows'], attrs['Cols'])
    attrs['filename'] = [dep, tas]
    dims = ('y', 'x')
    y = np.linspace(attrs['South'], attrs['North'], attrs['Rows'] + 1)[:-1]
    x = np.linspace(attrs['East'], attrs['West'], attrs['Cols'] + 1)[:-1]
    coords = dict((('x', x), ('y', y)))
    return xr.DataArray(val, coords=coords, dims=dims, attrs=attrs)


def data_array_to_dep(arr, fname=None, tag=None):

    val = arr.values
    typ_str, dtype = _get_dtype(val.dtype.name)
    val = val.astype('<' + dtype)
    attrs = case_insensitive_attrs(arr.attrs, typ_str)
    attrs['byte_order'] = 'LITTLE_ENDIAN'
    if val.ndim != 2 or attrs.get('stacks') > 1:
        not_2d_error()
    if not fname:
        tag = str(tag)
        fname = os.path.join(WHITEBOX_TEMP_DIR, tag)
    dep, tas = fname + '.dep', fname + '.tas'
    with open(dep, 'w') as f:
        metadata_entry = attrs.get('metadata_entry', '')
        at = attrs.copy()
        at['metadata_entry'] = ''.join('\nMetadata Entry: {}'.format(m)
                                       for m in metadata_entry.splitlines())
        f.write(DEP_TEMPLATE.format(**at))
    to_tas(val, typ_str, tas)
    return dep, tas


def xarray_whitebox_io(func, **kwargs):
    load_afterwards = {}
    delete_tempdir = kwargs.pop('delete_tempdir', True)
    fnames = {}
    dumped_an_xarray = False
    print('kw', kwargs)
    for k, v in kwargs.items():
        if k in INPUT_ARGS:
            print('k in INPUT_ARGS')
            if isinstance(v, strings):
                kwargs[k] = fix_path(v)
                print('Fix path', k)
            elif isinstance(v, xr.Dataset):
                if k == 'input':
                    raise ValueError('Cannot use xarray.Dataset unless the tool allows --inputs.  Here --input was used, and the tool must be called for each xarray.DataArray')
                print('DATASET')
                for k2 in v.data_vars:
                    print('k2', k2)
                    data_arr = getattr(v, k2)
                    dep, tas = data_array_to_dep(data_arr, tag=k2)
                    fnames[(k, k2)] = [dep, tas]
                kwargs[k] = ', '.join(dep for (k1, k2), (dep, tas) in fnames.items()
                                      if k1 == k)
                print('kw2', kwargs)
                dumped_an_xarray = k
            elif isinstance(v, xr.DataArray):
                kwargs[k] = data_array_to_dep(v, tag=k)[0]
                print('DataArray', k)
                dumped_an_xarray = k
        elif k in OUTPUT_ARGS:
            print('k in output_args', k)
            load_afterwards[k] = fix_path(v)
    if not load_afterwards and dumped_an_xarray:
        output_fname = kwargs[dumped_an_xarray].replace('.dep', '-output.dep')
        load_afterwards[k] = kwargs['output'] = output_fname
    def delayed_load_later(ret_val):
        if not load_afterwards:
            return ret_val
        data_arrs = {}
        attrs = dict(kwargs=kwargs, return_code=ret_val)

        for k, paths in load_afterwards.items():
            print('load after', k)
            for path in paths.split(', '):
                print('from_dep', path)
                data_arrs[k] = from_dep(path)
                data_arrs[k].attrs.update(attrs)
        dset = assign_nodata(xr.Dataset(data_arrs, attrs=attrs))
        for dep, tas in fnames.values():
            for fname in (dep, tas):
                os.remove(fname)
        if len(load_afterwards) == 1:
            return dset[k] # DataArray
        return dset        # Dataset - TODO implment later for multi output?
    return delayed_load_later, kwargs

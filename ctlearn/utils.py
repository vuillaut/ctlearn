import importlib
import logging
import os
import pkg_resources
import sys
import time

import numpy as np
import pandas as pd
import yaml

def setup_logging(config, log_dir, debug, log_to_file):

    # Log configuration to a text file in the log dir
    time_str = time.strftime('%Y%m%d_%H%M%S')
    config_filename = os.path.join(log_dir, time_str + '_config.yml')
    with open(config_filename, 'w') as outfile:
        ctlearn_version = pkg_resources.get_distribution("ctlearn").version
        outfile.write('# Training performed with '
                      'CTLearn version {}.\n'.format(ctlearn_version))
        yaml.dump(config, outfile, default_flow_style=False)

    # Set up logger
    logger = logging.getLogger()

    if debug:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    logger.handlers = [] # remove existing handlers from any previous runs
    if not log_to_file:
        handler = logging.StreamHandler()
    else:
        logging_filename = os.path.join(log_dir, time_str + '_logfile.log')
        handler = logging.FileHandler(logging_filename)
    handler.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))
    logger.addHandler(handler)

    return logger
    
    
def setup_DL1DataReader(config, mode):
    # Parse file list or prediction file list
    if mode in ['train', 'load_only']:
        if isinstance(config['Data']['file_list'], str):
            data_files = []
            with open(config['Data']['file_list']) as f:
                for line in f:
                    line = line.strip()
                    if line and line[0] != "#":
                        data_files.append(line)
            config['Data']['file_list'] = data_files
        if not isinstance(config['Data']['file_list'], list):
            raise ValueError("Invalid file list '{}'. "
                             "Must be list or path to file".format(config['Data']['file_list']))
    else:
        file_list = config['Prediction']['prediction_file_lists'][config['Prediction']['prediction_label']]
        if file_list.endswith(".txt"):
            data_files = []
            with open(file_list) as f:
                for line in f:
                    line = line.strip()
                    if line and line[0] != "#":
                        data_files.append(line)
            config['Data']['file_list'] = data_files
        elif file_list.endswith(".h5"):
            config['Data']['file_list'] = [file_list]
        if not isinstance(config['Data']['file_list'], list):
            raise ValueError("Invalid prediction file list '{}'. "
                             "Must be list or path to file".format(file_list))

    data_format = config.get('Data_format', 'stage1')
    allow_overwrite = config['Data'].get('allow_overwrite', True)
    del config['Data']['allow_overwrite']
    
    tasks = config['Tasks']
    transformations = []
    event_info = []
    if data_format == 'dl1dh':
        # Parse list of event selection filters
        event_selection = {}
        for s in config['Data'].get('event_selection', {}):
            s = {'module': 'dl1_data_handler.filters', **s}
            filter_fn, filter_params = load_from_module(**s)
            event_selection[filter_fn] = filter_params
        config['Data']['event_selection'] = event_selection

        # Parse list of image selection filters
        image_selection = {}
        for s in config['Data'].get('image_selection', {}):
            s = {'module': 'dl1_data_handler.filters', **s}
            filter_fn, filter_params = load_from_module(**s)
            image_selection[filter_fn] = filter_params
        config['Data']['image_selection'] = image_selection
        
        # Need to check this
        if 'particletype' in tasks:
            event_info.append('shower_primary_id')
            transformations.append({'name': 'ShowerPrimaryID', 'args': {'name': 'particletype', 'particle_id_col_name': 'shower_primary_id'}})
        if 'energy' in tasks:
            event_info.append('mc_energy')
            transformations.append({'name': 'MCEnergy', 'args': {'energy_col_name': 'mc_energy'}})
        if 'direction' in tasks:
            event_info.append('alt')
            event_info.append('az')
            transformations.append({'name': 'AltAz', 'args': {'alt_col_name': 'alt', 'az_col_name': 'az', 'deg2rad': False}})

    else:
        if 'particletype' in tasks:
            event_info.append('true_shower_primary_id')
            transformations.append({'name': 'ShowerPrimaryID'})
        if 'energy' in tasks:
            event_info.append('true_energy')
            transformations.append({'name': 'MCEnergy'})
        if 'direction' in tasks:
            event_info.append('true_alt')
            event_info.append('true_az')
            transformations.append({'name': 'DeltaAltAz_fix_subarray'})
            
    if allow_overwrite:
        config['Data']['event_info'] = event_info
    else:
        transformations = config['Data'].get('transforms', {})
    
    transforms = []
    # Parse list of Transforms
    for t in transformations:
        t = {'module': 'dl1_data_handler.transforms', **t}
        transform, args = load_from_module(**t)
        transforms.append(transform(**args))
    config['Data']['transforms'] = transforms

    # Convert interpolation image shapes from lists to tuples, if present
    if 'interpolation_image_shape' in config['Data'].get('mapping_settings',{}):
        config['Data']['mapping_settings']['interpolation_image_shape'] = {k: tuple(l) for k, l in config['Data']['mapping_settings']['interpolation_image_shape'].items()}


    # Possibly add additional info to load if predicting to write later
    if mode == 'predict':

        if 'Prediction' not in config:
            config['Prediction'] = {}

        if config['Prediction'].get('save_identifiers', False):
            if 'event_info' not in config['Data']:
                config['Data']['event_info'] = []
            config['Data']['event_info'].extend(['event_id', 'obs_id'])
            if config['Data']['mode'] == 'mono':
                if 'array_info' not in config['Data']:
                    config['Data']['array_info'] = []
                config['Data']['array_info'].append('id')

    return config['Data']

def load_from_module(name, module, path=None, args=None):
    if path is not None and path not in sys.path:
        sys.path.append(path)
    mod = importlib.import_module(module)
    fn = getattr(mod, name)
    params = args if args is not None else {}
    return fn, params

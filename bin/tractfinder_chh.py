#!/usr/bin/env python3

# Copyright (c) 2008-2023 the MRtrix3 contributors.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Covered Software is provided under this License on an "as is"
# basis, without warranty of any kind, either expressed, implied, or
# statutory, including, without limitation, warranties that the
# Covered Software is free of defects, merchantable, fit for a
# particular purpose or non-infringing.
# See the Mozilla Public License v. 2.0 for more details.
#
# For more details, see http://www.mrtrix.org/.

# Script for mapping fibre bundles based on provided tract orientation atlas[es]
# Written by Fiona Young, 2023

import os, shutil, copy
from argparse import Action

MAP_SUFFIX = '_tractmap'
DOF = 12
_GIT_VERSION = 'unknown'

def usage(cmdline): #pylint: disable=unused-variable
  from mrtrix3 import app #pylint: disable=no-name-in-module, import-outside-toplevel
  global _GIT_VERSION
  _GIT_VERSION = cmdline._git_version # cheeky

  cmdline.set_author('Fiona Young (fiona.young.15@ucl.ac.uk)')
  cmdline.set_synopsis('Map fibre bundles based on tract orientation atlas(es)')
  # cmdline.add_description('')

  cmdline.add_argument('input', help='the input FOD image')
  cmdline.add_argument('arg_pairs', metavar='atlas output [atlas output ...]', nargs='+', help='pairs of atlas / output images. If only one of each is specified and both are directories, all atlas present in the first directory will be mapped and the results will be stored in the second.')

  # Virtue options
  virtue_options = cmdline.add_argument_group('Tumour deformation modelling options')
  virtue_options.add_argument('-tumour', metavar='image', help='Provide tumour mask. This argument is required and sufficient to trigger deformation modelling')
  virtue_options.add_argument('-k', metavar='type', help='Type of deformation to model. If using exponential_constant, -l is required. Options are: linear, exponential, exponential_constant (default: exponential)',
                                choices=['linear', 'exponential', 'exponential_constant'], default='exponential')
  virtue_options.add_argument('-scale', metavar='fraction', type=float, default=1, help='Tumour scale factor (formerly squishfactor) (default: 1)')
  virtue_options.add_argument('-distance_lookup', metavar='directory', help='Location for storing/reusing Dt/Db lookup matrices for deformation algorithm (will be created if doesn\'t already exist). Recommended for speedup if recomputing deformation')
  virtue_options.add_argument('-l', metavar='value', help=('Specify a value for the expenential decay lambda. When using -k exponential, '
                                                         + 'the provided value imposes an upper bound on the dynamically determined lambda. '
                                                         + 'When using -k exponential_constant, lambda is globally set to the given value. '
                                                         + 'Note that in the latter case, a high value may result in weak deformation and the strictly '
                                                         + 'non-infiltrating condition may be violated (see Young et al. 2022 for further explanation).'),
                                                         default=-1, type=float)
  virtue_options.add_argument('-deformation_field', metavar='image', help='Store computed tumour deformation field. Can be applied to image')
  virtue_options.add_argument('-deformation_only', action='store_true', help='Only compute tumour deformation modelling, then exit.')

  #added by chhiara
  virtue_options.add_argument('-deformation_field_forward', metavar='image', help='Store forward computed tumour deformation field. Can be applied to tractography')

  # General options
  common_options = cmdline.add_argument_group('General tractfinder options')
  common_options.add_argument('-transform', help='provide transformation from atlas space to subject space')
  common_options.add_argument('-struct', metavar='template subject', nargs=2, help='provide structural images in template (=atlas) and subject space for coregistration. Note: the subject image is assumed to be adequately coregistered with the diffusion space, and the template image is assumed to be masked')
  common_options.add_argument('-premasked', action='store_true', help='indicate that the input structural image has been brain masked (otherwise script will perform brain extraction.) Note: the structural image in template space is ALWAYS assumed to be masked')
  common_options.add_argument('-brain_mask', metavar='image', help='Provide brain mask. If not provided, will attempt to estimate brain mask based on input FOD image (this is flakey!)')
  common_options.add_argument('-binary', nargs='?', const=0.05,  help='threshold tractmap to binary segmentation (default value: 0.05)')
  common_options.add_argument('-suffix', default=MAP_SUFFIX, help=f'define a suffix to append to each output (relevant only in directory input/output mode) (default: {MAP_SUFFIX}')
  common_options.add_argument('-template', help='Provide a template image to define the voxel grid of the output maps/segmentations. By default, the grid of the FOD input is used.')
  common_options.add_argument('-nii', '-nii.gz', '-mif.gz', nargs=0, action=StoreGiven, dest='fmt', default='mif', help='write output files in NIfTI or compressed MRtrix3 format instead of the default .mif (valid only for directory input/output)')

  # Citations
  cmdline.add_citation('Young, F., Aquilina, K., A Clark, C., & D Clayden, J. (2022). Fibre tract segmentation for intraoperative diffusion MRI in neurosurgical patients using tract-specific orientation atlas and tumour deformation modelling. International journal of computer assisted radiology and surgery, 17(9), 1559–1567. https://doi.org/10.1007/s11548-022-02617-z')
  cmdline.add_citation('Nowinski, W. L., & Belov, D. (2005). Toward atlas-assisted automatic interpretation of MRI morphological brain scans in the presence of tumor. Academic radiology, 12(8), 1049–1057. https://doi.org/10.1016/j.acra.2005.04.018')
  cmdline.add_citation('Jenkinson, M., Bannister, P., Brady, J. M. and Smith, S. M. Improved Optimisation for the Robust and Accurate Linear Registration and Motion Correction of Brain Images. NeuroImage, 17(2), 825-841, 2002.', condition='If performing registration (i.e. -transform option not provided)', is_external=True)
  cmdline.add_citation('Smith, S. M. Fast robust automated brain extraction. Human Brain Mapping, 17(3), 143-155, 2002.', condition='If relying on the script to generate a brain mask (either for registration or tumour deformation modelling)', is_external=True)

# Custom argparse action for detecting which option string provided
# and storing that as argument value
class StoreGiven(Action):
    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, dest, **kwargs)
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, option_string.lstrip('-'))

# "Overloaded" from mrtrix3.path.make_dir to check if existing file is a directory
# Make a directory if it doesn't exist; don't do anything if it does already exist
def make_dir(path):
  from mrtrix3 import app, MRtrixError
  import errno
  try:
    os.makedirs(path)
    app.debug('Created directory ' + path)
  except OSError as exception:
    if exception.errno != errno.EEXIST:
      raise
    elif not os.path.isdir(path):
      raise MRtrixError('Path \'' + path + '\' exists and is not a directory')
    app.debug('Directory \'' + path + '\' already exists')

# adapt behaviour of flag_mutually_exclusive_options() which is not suitable here,
# as want to check at least one provided, but not mutex. Ignore the "value is different from default"
# check here: required arguments shouldn't have defaults
def check_from_required(parser, args_in, required_args):
  count = sum([bool(getattr(args_in, option, False)) for option in required_args])
  if not count:
    parser.error('One of the following options must be provided: ' + ', '.join([ '-' + o for o in required_args ]))

# Have defined this, rather than make use of pathlib for full 3.x compatibility
def pure_stem(pathstr):
  stem, ext = os.path.splitext(os.path.basename(pathstr))
  while ext: stem, ext = os.path.splitext(stem)
  return stem

def execute():
  from mrtrix3 import MRtrixError
  from mrtrix3 import app, image, path, run, fsl, sys, __version__
  if app.ARGS.tumour:
    from tractfinder import virtue
  cmdstring = ' '.join(sys.argv) + f' (tractfinder version={_GIT_VERSION}, mrtrix version={__version__}) '

  if not app.ARGS.deformation_only:
    check_from_required(app.CMDLINE, app.ARGS, ['transform', 'struct'])
  if app.ARGS.tumour and app.ARGS.k == 'exponential_constant' and not app.ARGS.l:
    app.CMDLINE.error('-l is required when using -k exponential_constant')

  ## What steps will we need to do?
  make_brain_mask = False
  if (app.ARGS.tumour or (not app.ARGS.transform and not app.ARGS.premasked)):
    # We've established we *need* a mask. Do we need to *make* one?
    if not app.ARGS.brain_mask:
      make_brain_mask = True
      if not app.ARGS.struct:
    ## TODO: if -struct and -premasked, allow that? then can threshold premasked ? but kinda dodgy, can't be sure what values will be outside the brain
        app.CMDLINE.error('A brain mask is required for either registration (-transform option not provided) or tumour deformation modelling (-tumour option provided). ' +
                          'Either provide one with -brain_mask or provide a structural image with -struct from which a mask can be generated.')

  atlas_paths = []
  output_paths = []

  ## Check and parse argument inputs
  if len(app.ARGS.arg_pairs) % 2:
    raise MRtrixError('command expects pairs of input tract atlas and output map images to be provided.')
  elif len(app.ARGS.arg_pairs) == 2:
    # Check if directories have been provided
    source, dest = app.ARGS.arg_pairs
    if os.path.isdir(source):
      app.debug('Atlas input is directory')
      make_dir(dest)
      for p in path.all_in_dir(source, dir_path=True):
        try:
          h = image.Header(p)
          if h.is_sh(): atlas_paths.append(p)
          else: app.console('Skipping non-SH input file \'' + h.name() + '\'')
        except MRtrixError: pass
      output_paths = [os.path.join(dest, pure_stem(in_path) + app.ARGS.suffix + f'.{app.ARGS.fmt}') for in_path in atlas_paths]
      for i, p in reversed(list(enumerate(copy.copy(output_paths)))):
        try: app.check_output_path(p)
        except MRtrixError:
          app.console('Skipping output file \'' + p + '\' (use -force to override)') # Should this be warn()?
          atlas_paths.pop(i)
          output_paths.pop(i)
        finally:
          if not (atlas_paths and output_paths):
            raise MRtrixError('No new outputs to create (use -force to overwrite contents of output directory) \'' + dest + '\'')
          if not len(set(output_paths)) == len(output_paths):
            raise MRtrixError('Non-unique atlas filenames present (after removing extensions). Could not create unique output filenames')
      app.debug(f'Creating {len(output_paths)} new files')
    else:
      app.check_output_path(dest)
      atlas_paths, output_paths = [source], [dest]
  else:
    # Arbitrary number of atlas / output pairs
    atlas_paths  = app.ARGS.arg_pairs[::2]
    output_paths = app.ARGS.arg_pairs[1::2]
    for p in output_paths:
      app.check_output_path(p)

  if app.ARGS.distance_lookup: make_dir(app.ARGS.distance_lookup)
  if app.ARGS.deformation_field: app.check_output_path(app.ARGS.deformation_field)

  ## Set up filenames and command strings
  bet_cmd = fsl.exe_name('bet')
  flirt_cmd = fsl.exe_name('flirt')
  fsl_suffix = fsl.suffix()

  mask_image_reg = 'brain_mask_reg.mif'
  mask_image_def = 'brain_mask_def.mif'
  tumour_mask = 'tumour_mask.mif'
  def_field_image = 'deformation_field.mif'
  struct_image = 'struct.nii.gz'
  bet_image = 'bet' + fsl_suffix



  app.make_scratch_dir()
  app.goto_scratch_dir()

  # Take strides from template (=atlas space) image, or brain mask, or default to 1,2,3
  strides = ( image.Header(path.from_user(app.ARGS.struct[0], False)).strides()
              if app.ARGS.struct else [1,2,3] )
  strides = ','.join(str(s) for s in strides)

  if app.ARGS.struct:
    run.command(f'mrconvert -strides {strides} '
              + f'{path.from_user(app.ARGS.struct[1])} {struct_image}', show=False)

  ## Brain mask: will be needed for either registration or deformation modelling.
  # Do we need to make one?
  if make_brain_mask:
    if app.ARGS.premasked:
      app.warn('Relying on a pre-masked structural image to produce a brain mask for tumour deformation is risky')
      run.command(f'mrthreshold {path.from_user(app.ARGS.struct[1])} -abs 0 -comparison gt - | '
                + f'mrgrid - regrid {mask_image_def} -strides {strides} -vox 1 -interp nearest -datatype bit', show=False)
      app.debug(f'{mask_image_def} created from struct image with strides {strides}')
    else:
      # BET madness ensues
      app.console('No brain mask provided, attempting to generate robust mask')
      ## Try can create a decent brain mask
      # Start with the FOD amplitude image, fill holes
      run.command('mrconvert -coord 3 0 ' + path.from_user(app.ARGS.input)
                   + ' - |  mrthreshold - -abs 0 -comparison gt fod_mask.nii.gz', show=False)
      run.command('fslmaths fod_mask.nii.gz -fillh fod_mask.nii.gz', show=False)
      # Smooth edges and regrid to structural space
      run.command('mrfilter fod_mask.nii.gz smooth -extent 5 - | '
               +  'mrthreshold - -abs 0.5 - | '
               + f'mrgrid - regrid fod_mask_smooth_regrid.mif '
               + f'-template {struct_image} -interp nearest -strides {strides}', show=False)
      # Dilate and use to roughly crop structural image. This is so that bet
      # has a better change of a clean segmentation without a bunch of neck etc.
      run.command('maskfilter fod_mask_smooth_regrid.mif dilate -npass 5 - | '
               + f'mrcalc - {struct_image} -mult struct_rough_masked.nii.gz', show=False)
      # Brain masking using bet
      run.command(f'{bet_cmd} struct_rough_masked.nii.gz {bet_image} -r 100 -m ', show=False)
      bet_image = fsl.find_image(bet_image)
      # If we also need this brain mask for tumour deformation down the line,
      # convert it now to the correct grid and crop image to reduce file size
      if app.ARGS.tumour:
        tmpfile = path.name_temporary('.mif')
        run.command(f'mrgrid bet_mask{fsl_suffix} regrid {tmpfile} -vox 1 -interp nearest -datatype bit', show=False)
        run.command(f'mrgrid {tmpfile} crop -mask {tmpfile} {mask_image_def} -datatype bit', show=False)

  ## Tumour deformation modelling
  if app.ARGS.tumour:
    app.console('Computing tumour deformation field')
    if app.ARGS.brain_mask:
      # Regrid and crop
      tmpfile = path.name_temporary('.mif')
      run.command(f'mrgrid {path.from_user(app.ARGS.brain_mask)} regrid {tmpfile} '
                 + '-vox 1 -interp nearest -datatype bit', show=False)
      run.command(f'mrgrid {tmpfile} crop -mask {tmpfile} {mask_image_def} '
                 + '-datatype bit', show=False)
    # Match tumour mask to brain mask grid
    run.command(f'mrgrid {path.from_user(app.ARGS.tumour)} regrid {tumour_mask} '
              + f'-template {mask_image_def} -interp nearest -datatype bit', show=False)
    
   
    #--added by chhiara    
    def_field_image_forward= 'deformation_field_forw.mif' if app.ARGS.deformation_field_forward else None
    
    #--added by chhiara    
    #to save both forward and inverse deformation field if not added only the defualt (inverse) is computed
    virtue.entry_point_chh(tumour_mask, mask_image_def, def_field_image,
                       def_field_forw= def_field_image_forward, #this is None if Arg deformation_field_forward is not provided
                       expon=None if app.ARGS.k=='linear' else app.ARGS.l,
                       expon_const=app.ARGS.k=='exponential_constant',
                       squish=app.ARGS.scale,
                       save_lookup=path.from_user(app.ARGS.distance_lookup) if app.ARGS.distance_lookup else None
                       ) 
    
    
    # commented by chhiara
    #to use original function 
    #virtue.entry_point(tumour_mask, mask_image_def, def_field_image,
    #                   expon=None if app.ARGS.k=='linear' else app.ARGS.l,
    #                   expon_const=app.ARGS.k=='exponential_constant',
    #                   squish=app.ARGS.scale,
    #                   save_lookup=path.from_user(app.ARGS.distance_lookup) if app.ARGS.distance_lookup else None)
    
    if app.ARGS.deformation_field:
      # Convert instead of move, incase different format requested
      run.command(f'mrconvert {def_field_image} {path.from_user(app.ARGS.deformation_field)} -set_property command_history "{cmdstring}"', force=app.FORCE_OVERWRITE, show=False)
    
    #added by chhiara
    if app.ARGS.deformation_field_forward:
      run.command(f'mrconvert {def_field_image_forward} {path.from_user(app.ARGS.deformation_field_forward)} -set_property command_history "{cmdstring}"', force=app.FORCE_OVERWRITE, show=False)
      
    if app.ARGS.deformation_only:
      return
  #--------------in deformation only the code stops here
  
  
  ## Registration
  if app.ARGS.transform:
    shutil.copy(path.from_user(app.ARGS.transform, False), 'transform.txt')

  else:
    if app.ARGS.premasked:
      run.command(f'mrconvert -strides {strides} '
                + f'{path.from_user(app.ARGS.struct[1])} {bet_image}', show=False)
    elif app.ARGS.brain_mask:
      run.command(f'mrgrid {path.from_user(app.ARGS.brain_mask)} regrid {mask_image_reg} '
                + f'-datatype bit -interp nearest -strides {strides} '
                + f'-template {struct_image}', show=False)
      run.command(f'mrcalc {mask_image_reg} {struct_image} -mult {bet_image}', show=False)

    # Actually run registration
    app.console(f'Running FLIRT registration with {DOF} degrees of freedom')
    run.command(f'{flirt_cmd} -in {path.from_user(app.ARGS.struct[0])} '
              + f'-ref {bet_image} '
              + f'-dof {DOF} -omat transform_flirt.txt')
    run.command(f'transformconvert transform_flirt.txt {path.from_user(app.ARGS.struct[0])} {bet_image} '
               + 'flirt_import transform.txt -quiet', show=False)

  # Finish masking / registration branching

  ## Cycle through all the atlases
  i, n = 1, len(atlas_paths)
  progress = app.ProgressBar(f'Mapping atlas {i} of {n} to subject')

  for atlas_path, output_path in zip(atlas_paths, output_paths):
    progress.increment(f'Mapping atlas {i} of {n} to subject')

    # Transform atlas
    transf_command_string = (f'mrtransform {path.from_user(atlas_path)} '
                             +'-linear transform.txt -reorient_fod yes ')
    if app.ARGS.tumour:
        app.console('Applying tumour deformation to atlas')
        # Regridding needs to happen separately, since the mrtransform -template
        # option is applied to the warp field. We'll split the pipe to allow progress increment
        transf_command_string += f'-warp {def_field_image} - '
        tmp_file = run.command(transf_command_string, show=False).stdout
        progress.increment()
        run.command(f'mrgrid {tmp_file} regrid -template {path.from_user(app.ARGS.input)} '
                    + path.to_scratch(f'atlas_{i}.mif'), show=False)

    else:
        app.console('Transforming atlas')
        transf_command_string += (f'-template {path.from_user(app.ARGS.input)} '
                                + path.to_scratch(f'atlas_{i}.mif'))
        run.command(transf_command_string, show=False)

    progress.increment()

    # Compute inner product
    ip_command_string = (f'mrcalc -quiet atlas_{i}.mif {path.from_user(app.ARGS.input)} -mult - | '
                         +'mrmath -quiet - sum -axis 3 - | ')
    if app.ARGS.template:
      app.console(f'Regridding output to match template image "{app.ARGS.template}"')
      ip_command_string += f'mrgrid - regrid -template {path.from_user(app.ARGS.template)} - | '
    if app.ARGS.binary:
      app.console(f'Binarising output with threshold {app.ARGS.binary}')
      ip_command_string += f'mrthreshold -abs {app.ARGS.binary} - - | '
    ip_command_string += f'mrconvert - {path.from_user(output_path)} -set_property command_history "{cmdstring}"'
    run.command(ip_command_string, show=False, force=app.FORCE_OVERWRITE)
    i += 1

  progress.done()

# Execute the script
import mrtrix3
mrtrix3.execute() #pylint: disable=no-member

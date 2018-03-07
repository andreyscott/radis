#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Mar  2 23:39:52 2018

@author: erwan
"""

from __future__ import absolute_import
from __future__ import print_function
import radis
from radis.misc.utils import DatabankNotFound
from radis.spectrum.rescale import get_redundant
from radis.tools.database import load_spec
from radis.test.utils import getTestFile
import numpy as np

def _test_compression__fast(verbose=True, warnings=True, *args, **kwargs):
    # Deactivated from pytest with _ for the moment, because neq is not public
    # TODO: convet _test_ to test_ once the SpectrumFactory is added in RADIS
    
    from neq.spec import SpectrumFactory
    
    Tgas = 1500
    sf = SpectrumFactory(
                         wavelength_min=4400,
                         wavelength_max=4800,
    #                     mole_fraction=1,
                         path_length=0.1,
                         mole_fraction=0.01,
                         cutoff=1e-25,
                         wstep = 0.005,
                         isotope=[1],
                         db_use_cached=True,
                         self_absorption=True,
                         verbose=False)
    try:
        sf.load_databank('HITRAN-CO-TEST')
    except DatabankNotFound:
        if warnings:
            import sys
            print((sys.exc_info()))
            print(('Testing spectrum.py: Database not defined: HITRAN-CO \n'+\
                           'Ignoring the test'))
        return True

    s1 = sf.non_eq_spectrum(Tgas, Tgas, path_length=0.01)
    redundant = get_redundant(s1)
    if verbose: print(redundant)
    
    assert redundant == {'emissivity_noslit': True, 'radiance_noslit': True, 
                         'radiance': True, 'emisscoeff': True, 
                         'transmittance_noslit': True, 'absorbance': True, 
                         'transmittance': True, 'abscoeff': False}
    
    return True


def test_update_transmittance__fast(verbose=True, warnings=True, *args, **kwargs):
    ''' Test that update can correctly recompute missing quantities '''
    # TODO: add one with radiance too
    
    # Work with a Spectrum object that was generated by Specair
    s = load_spec(getTestFile('N2C_specair_380nm.spec'))
    w1, T1 = s.get('transmittance_noslit')   # our reference
    
    if verbose:
        debug_mode = radis.DEBUG_MODE  # shows all the rescale steps taken
        radis.DEBUG_MODE=True
    
    # Now let's apply some update() steps
    
    # 1) Make sure updating doesnt change anything
    s.update()
    w2, T2 = s.get('transmittance_noslit')
    
    # 2) Now recompute from abscoeff
    del s._q['transmittance_noslit']
    s.update()
    w2, T3 = s.get('transmittance_noslit')
    
    # 3) Now recompute from absorbance
    del s._q['transmittance_noslit']
    del s._q['abscoeff']
    s.update()
    w2, T4 = s.get('transmittance_noslit')

    if verbose:
        radis.DEBUG_MODE = debug_mode

    # Compare    
    assert np.allclose(T1, T2)
    assert np.allclose(T1, T3)
    assert np.allclose(T1, T4)
    
    return True


def _run_all_tests(verbose=True, warnings=True, *args, **kwargs):
    _test_compression__fast(verbose=verbose, warnings=warnings, *args, **kwargs)
    test_update_transmittance__fast(verbose=verbose, warnings=warnings, *args, **kwargs)
    
    return True

if __name__ == '__main__':
    print(('Testing test_rescale.py:', _run_all_tests(verbose=True)))
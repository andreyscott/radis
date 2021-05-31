import ctypes

##import pickle
from os.path import join

import cupy as cp
import numpy as np
from scipy.constants import N_A, c, h, k

c_cm = 100 * c
c2 = h * c_cm / k

from radis.misc.utils import getProjectRoot


class initData(ctypes.Structure):
    _fields_ = [
        ("v_min", ctypes.c_float),
        ("v_max", ctypes.c_float),
        ("dv", ctypes.c_float),
        ("N_v", ctypes.c_int),
        ("N_wG", ctypes.c_int),
        ("N_wL", ctypes.c_int),
        ("N_wG_x_N_wL", ctypes.c_int),
        ("N_total", ctypes.c_int),
        ("Max_lines", ctypes.c_int),
        ("N_lines", ctypes.c_int),
        ("N_points_per_block", ctypes.c_int),
        ("N_threads_per_block", ctypes.c_int),
        ("N_blocks_per_grid", ctypes.c_int),
        ("N_points_per_thread", ctypes.c_int),
        ("N_iterations_per_thread", ctypes.c_int),
        ("shared_size_floats", ctypes.c_int),
    ]


class iterData(ctypes.Structure):
    _fields_ = [
        ("p", ctypes.c_float),
        ("log_p", ctypes.c_float),
        ("hlog_T", ctypes.c_float),
        ("log_rT", ctypes.c_float),
        ("c2T", ctypes.c_float),
        ("N", ctypes.c_float),
        ("l", ctypes.c_float),
        ("slit_FWHM", ctypes.c_float),
        ("log_wG_min", ctypes.c_float),
        ("log_wL_min", ctypes.c_float),
        ("log_dwG", ctypes.c_float),
        ("log_dwL", ctypes.c_float),
        ("log_c2Mm", ctypes.c_float * 16),
    ]


init_params_h = initData()
iter_params_h = iterData()

cuda_fname = join(getProjectRoot(), "lbl", "gpu.cpp")
with open(cuda_fname, "rb") as f:
    cuda_code = f.read().decode()

cuda_module = cp.RawModule(code=cuda_code)
cu_fillDLM = cuda_module.get_function("fillDLM")
cu_applyLineshapes = cuda_module.get_function("applyLineshapes")
cu_calcTransmittanceNoslit = cuda_module.get_function("calcTransmittanceNoslit")
cu_applyGaussianSlit = cuda_module.get_function("applyGaussianSlit")


def py_calc_lorentzian_envelope_params(na, log_2gs, verbose=False):
    # Remove duplicates
    unique_lines = set([])
    for i in range(len(na)):
        unique_lines.add(str(na[i]) + " " + str(log_2gs[i]))

    # Only keep extremes
    max_dict = {}
    min_dict = {}
    for s in unique_lines:
        na_i, log_2gs_i = map(float, s.split())
        try:
            min_dict[na_i] = log_2gs_i if log_2gs_i < min_dict[na_i] else min_dict[na_i]
            max_dict[na_i] = log_2gs_i if log_2gs_i > max_dict[na_i] else max_dict[na_i]

        except (KeyError):
            min_dict[na_i] = log_2gs_i
            max_dict[na_i] = log_2gs_i

    # Check which ones are really at the top:
    result = []
    for test_dict in (min_dict, max_dict):

        keys = sorted(test_dict.keys(), reverse=(test_dict == min_dict))
        A = [keys[0]]
        B = [test_dict[keys[0]]]
        X = [-np.inf]

        for key in keys[1:]:
            for i in range(len(X)):
                xi = (test_dict[key] - B[i]) / (A[i] - key)
                if xi >= X[i]:
                    if i < len(X) - 1:
                        if xi < X[i + 1]:
                            break
                    else:
                        break

            A = A[: i + 1] + [key]
            B = B[: i + 1] + [test_dict[key]]
            X = X[: i + 1] + [xi]

        X = X[1:] + [np.inf]
        result.append((A, B, X))

    return tuple(result)


def py_calc_gaussian_envelope_params(log_2vMm, verbose=False):
    return np.amin(log_2vMm), np.max(log_2vMm)


try:
    from radis_cython_extensions import (
        calc_gaussian_envelope_params,
        calc_lorentzian_envelope_params,
    )
except (ModuleNotFoundError):
    calc_gaussian_envelope_params = py_calc_gaussian_envelope_params
    calc_lorentzian_envelope_params = py_calc_lorentzian_envelope_params


def init_gaussian_params(log_2vMm, verbose_gpu):

    if verbose_gpu >= 2:
        print("Initializing Gaussian parameters")

    ##fname = "Gaussian_minmax_" + str(len(log_2vMm)) + ".dat"
    ##    try:
    ##        param_data = pickle.load(open(fname, "rb"))
    ##        if verbose_gpu >= 2:
    ##            print(" (from cache)... ")
    ##
    ##    except (OSError, IOError):
    if True:
        if verbose_gpu >= 2:
            print("... ")

        param_data = calc_gaussian_envelope_params(log_2vMm, verbose_gpu)
    ##        pickle.dump(param_data, open(fname, "wb"))

    if verbose_gpu >= 2:
        print("done!")

    return param_data


def init_lorentzian_params(na, log_2gs, verbose_gpu):

    if verbose_gpu >= 2:
        print("Initializing Lorentzian parameters ")

    ##fname = "Lorenzian_minmax_" + str(len(log_2gs)) + ".dat"
    ##
    ##    try:
    ##        with open(fname, "rb") as f:
    ##            if verbose_gpu >= 2:
    ##                print(" (from cache)... ")
    ##            param_data = pickle.load(f)
    ##
    ##    except:
    if True:
        if verbose_gpu >= 2:
            print(" ... ")

        param_data = calc_lorentzian_envelope_params(na, log_2gs, verbose_gpu)
    ##        with open(fname, "wb") as f:
    ##            pickle.dump(param_data, f)

    if verbose_gpu >= 2:
        print("done!")

    return param_data


def calc_gaussian_params(
    gaussian_param_data, init_params_h, iter_params_h, epsilon=1e-4
):

    host_params_h_log_2vMm_min, host_params_h_log_2vMm_max = gaussian_param_data
    log_wG_min = host_params_h_log_2vMm_min + iter_params_h.hlog_T
    log_wG_max = host_params_h_log_2vMm_max + iter_params_h.hlog_T
    ##    print("wG:", log_wG_min, log_wG_max)
    log_wG_max += epsilon
    log_dwG = (log_wG_max - log_wG_min) / (init_params_h.N_wG - 1)

    iter_params_h.log_wG_min = log_wG_min
    iter_params_h.log_dwG = log_dwG


def calc_lorentzian_minmax(param_data, log_rT, log_p):

    result = []
    for params in param_data:
        A, B, X = params
        i = 0
        while X[i] < log_rT:
            i += 1
        result.append(log_rT * A[i] + B[i] + log_p)
    return tuple(result)


def calc_lorentzian_params(param_data, init_params_h, iter_params_h, epsilon=1e-4):

    log_wL_min, log_wL_max = calc_lorentzian_minmax(
        param_data, iter_params_h.log_rT, iter_params_h.log_p
    )
    ##    print("wL:", log_wL_min, log_wL_max)
    log_wL_max += epsilon
    log_dwL = (log_wL_max - log_wL_min) / (init_params_h.N_wL - 1)

    iter_params_h.log_wL_min = log_wL_min
    iter_params_h.log_dwL = log_dwL


def set_pT(p, T, mole_fraction, iter_params_h, l=1.0, slit_FWHM=0.0):

    iter_params_h.p = p  # bar
    iter_params_h.log_p = np.log(p)
    iter_params_h.hlog_T = 0.5 * np.log(T)
    iter_params_h.log_rT = np.log(296.0 / T)
    iter_params_h.c2T = -c2 / T
    iter_params_h.N = mole_fraction * p * 1e5 / (1e6 * k * T)  # cm-3
    iter_params_h.l = l
    iter_params_h.slit_FWHM = slit_FWHM
    iter_params_h.log_c2Mm[0] = (
        np.log(2) + 0.5 * np.log(2 * k * np.log(2)) - np.log(c ** 2 * 44e-3 / N_A)
    )
    iter_params_h.log_c2Mm[1] = (
        np.log(2) + 0.5 * np.log(2 * k * np.log(2)) - np.log(c ** 2 * 45e-3 / N_A)
    )
    iter_params_h.log_c2Mm[2] = (
        np.log(2) + 0.5 * np.log(2 * k * np.log(2)) - np.log(c ** 2 * 46e-3 / N_A)
    )


def constant_memory_setter(var_str):
    def setter(var_h):
        memptr_d = cuda_module.get_global(var_str)
        ptr = ctypes.cast(ctypes.pointer(var_h), ctypes.c_void_p)
        struct_size = ctypes.sizeof(var_h)
        memptr_d.copy_from_host(ptr, struct_size)

    return setter


def gpu_init(
    v_arr,
    N_wG,
    N_wL,
    iso,
    v0,
    da,
    log_2gs,
    na,
    log_2vMm,
    S0,
    El,
    Q,
    verbose_gpu=True,
    gpu=True,
):

    # ----------- setup global variables -----------------
    global init_params_h
    global host_params_h_dec_size
    global host_params_h_block_preparation_step_size
    global host_params_h_iso_d
    global host_params_h_v0_d
    global host_params_h_da_d
    ##    global host_params_h_v0_dec
    ##    global host_params_h_da_dec
    global host_params_h_S0_d
    global host_params_h_El_d
    global host_params_h_Q_d
    global host_params_h_log_2gs_d
    global host_params_h_na_d

    global host_params_h_DLM_d_in
    global host_params_h_spectrum_d_in
    global host_params_h_transmittance_noslit
    global host_params_h_transmittance_FT

    global lorentzian_param_data
    global gaussian_param_data

    global cuda_module
    global database_path
    global N_lines_to_load
    # -----------------------------------------------------

    if gpu:
        from cupy import array, complex64, float32, zeros

        set_init_params = constant_memory_setter("init_params_d")
    else:
        from numpy import complex64, float32, zeros

        array = lambda arr: arr
        from radis_cython_extensions import set_init_params

    init_params_h.v_min = np.min(v_arr)  # 2000.0
    init_params_h.v_max = np.max(v_arr)  # 2400.0
    init_params_h.dv = (v_arr[-1] - v_arr[0]) / (len(v_arr) - 1)  # 0.002
    init_params_h.N_v = len(v_arr)
    init_params_h.N_wG = N_wG
    init_params_h.N_wL = N_wL

    init_params_h.N_iterations_per_thread = 1024
    host_params_h_block_preparation_step_size = 128

    host_params_h_shared_size = 0x8000  # Bytes - Size of the shared memory
    init_params_h.shared_size_floats = host_params_h_shared_size // 4  # size of float

    init_params_h.N_wG_x_N_wL = init_params_h.N_wG * init_params_h.N_wL
    init_params_h.N_total = init_params_h.N_wG_x_N_wL * init_params_h.N_v
    init_params_h.N_points_per_block = (
        init_params_h.shared_size_floats // init_params_h.N_wG_x_N_wL
    )

    init_params_h.N_threads_per_block = 1024
    init_params_h.N_blocks_per_grid = 4 * 256 * 256
    init_params_h.N_points_per_thread = (
        init_params_h.N_points_per_block // init_params_h.N_threads_per_block
    )

    if verbose_gpu >= 2:
        print()
        print(
            "Spectral points per block  : {0}".format(init_params_h.N_points_per_block)
        )
        print(
            "Threads per block          : {0}".format(init_params_h.N_threads_per_block)
        )
        print(
            "Spectral points per thread : {0}".format(init_params_h.N_points_per_thread)
        )
        print()

    lorentzian_param_data = init_lorentzian_params(na, log_2gs, verbose_gpu)
    gaussian_param_data = init_gaussian_params(log_2vMm, verbose_gpu)
    init_params_h.N_lines = int(len(v0))

    if verbose_gpu == 1:
        print("Number of lines loaded: {0}".format(init_params_h.N_lines))
        print()

    if verbose_gpu >= 2:
        print("Allocating device memory and copying data...")

    host_params_h_DLM_d_in = zeros(
        (2 * init_params_h.N_v, init_params_h.N_wG, init_params_h.N_wL),
        order="C",
        dtype=float32,
    )
    host_params_h_spectrum_d_in = zeros(init_params_h.N_v + 1, dtype=complex64)
    host_params_h_transmittance_noslit = zeros(init_params_h.N_v * 2, dtype=float32)
    host_params_h_transmittance_FT = zeros(init_params_h.N_v + 1, dtype=complex64)

    if verbose_gpu >= 2:
        print("Copying initialization parameters to device memory...")
    set_init_params(init_params_h)

    if verbose_gpu >= 2:
        print("done!")
        print("Copying spectral data to device memory...")

    # #Copy spectral data to device
    host_params_h_iso_d = array(iso)
    host_params_h_v0_d = array(v0)
    host_params_h_da_d = array(da)
    host_params_h_S0_d = array(S0)
    host_params_h_El_d = array(El)
    host_params_h_log_2gs_d = array(log_2gs)
    host_params_h_na_d = array(na)
    host_params_h_Q_d = array(Q)

    if verbose_gpu >= 2:
        print("done!")


def gpu_iterate(p, T, mole_fraction, verbose_gpu=True, l=1.0, slit_FWHM=0.0, gpu=True):

    # ----------- setup global variables -----------------

    global host_params_h_start

    global init_params_h, iter_params_h
    global host_params_h_iso
    global host_params_h_v0_d
    global host_params_h_da_d
    global host_params_h_S0_d
    global host_params_h_El_d
    global host_params_h_Q_d
    global host_params_h_log_2gs_d
    global host_params_h_na_d
    global host_params_h_stop
    global host_params_h_elapsedTime

    global host_params_h_DLM_d_in
    global host_params_h_spectrum_d_in
    global host_params_h_transmittance_noslit
    global host_params_h_transmittance_FT

    global cuda_module
    ##    global host_params_h_v0_dec
    ##    global host_params_h_da_dec
    global DLM
    # ------------------------------------------------------

    if gpu:
        from cupy import complex64, float32
        from cupy.fft import irfft, rfft

        fillDLM = cu_fillDLM
        applyLineshapes = cu_applyLineshapes
        calcTransmittanceNoslit = cu_calcTransmittanceNoslit
        applyGaussianSlit = cu_applyGaussianSlit
        set_iter_params = constant_memory_setter("iter_params_d")
        asnumpy = cp.asnumpy

    else:
        from numpy import complex64, float32
        from numpy.fft import irfft, rfft

        from radis_cython_extensions import (
            applyGaussianSlit,
            applyLineshapes,
            calcTransmittanceNoslit,
            fillDLM,
            get_T,
            set_iter_params,
        )

        asnumpy = np.array

    if verbose_gpu >= 2:
        print("Copying iteration parameters to device...")

    set_pT(p, T, mole_fraction, iter_params_h, l=l, slit_FWHM=slit_FWHM)

    calc_gaussian_params(
        gaussian_param_data,
        init_params_h,
        iter_params_h,
    )

    calc_lorentzian_params(
        lorentzian_param_data,
        init_params_h,
        iter_params_h,
    )

    set_iter_params(iter_params_h)
    if not gpu:
        print("T:", get_T())

    if verbose_gpu >= 2:
        print("done!")
        print("Filling DLM...")

    host_params_h_DLM_d_in.fill(0)
    host_params_h_spectrum_d_in.fill(0)
    host_params_h_transmittance_FT.fill(0)

    n_threads = init_params_h.N_threads_per_block
    n_blocks = (
        init_params_h.N_lines // (n_threads * init_params_h.N_iterations_per_thread) + 1
    )

    fillDLM(
        (n_blocks,),
        (n_threads,),
        (
            host_params_h_iso_d,
            host_params_h_v0_d,
            host_params_h_da_d,
            host_params_h_S0_d,
            host_params_h_El_d,
            host_params_h_log_2gs_d,
            host_params_h_na_d,
            host_params_h_DLM_d_in,
            host_params_h_Q_d,
        ),
    )
    if gpu:
        cp.cuda.runtime.deviceSynchronize()

    if verbose_gpu >= 2:
        print("Applying lineshapes...")

    host_params_h_DLM_d_out = rfft(host_params_h_DLM_d_in, axis=0).astype(complex64)

    if gpu:
        cp.cuda.runtime.deviceSynchronize()

    n_threads = init_params_h.N_threads_per_block
    n_blocks = (init_params_h.N_v + 1) // n_threads + 1
    applyLineshapes(
        (n_blocks,),
        (n_threads,),
        (
            host_params_h_DLM_d_out,
            host_params_h_spectrum_d_in,
        ),
    )

    if gpu:
        cp.cuda.runtime.deviceSynchronize()

    host_params_h_spectrum_d_out = irfft(host_params_h_spectrum_d_in).astype(float32)

    if gpu:
        cp.cuda.runtime.deviceSynchronize()

    if verbose_gpu >= 2:
        print("Done!")
        print("Calculating transmittance...")

    abscoeff_h = asnumpy(host_params_h_spectrum_d_out)[: init_params_h.N_v]

    ## Calc transmittance_noslit:
    n_threads = init_params_h.N_threads_per_block
    n_blocks = (2 * init_params_h.N_v) // n_threads + 1
    calcTransmittanceNoslit(
        (n_blocks,),
        (n_threads,),
        (host_params_h_spectrum_d_out, host_params_h_transmittance_noslit),
    )

    if gpu:
        cp.cuda.runtime.deviceSynchronize()

    if verbose_gpu >= 2:
        print("Done!")
        print("Applying slit function...")

    ## Apply slit function:
    host_params_h_transmittance_noslit_FT = rfft(
        host_params_h_transmittance_noslit
    ).astype(complex64)

    if gpu:
        cp.cuda.runtime.deviceSynchronize()

    n_threads = init_params_h.N_threads_per_block
    n_blocks = (init_params_h.N_v + 1) // n_threads + 1
    applyGaussianSlit(
        (n_blocks,),
        (n_threads,),
        (host_params_h_transmittance_noslit_FT, host_params_h_transmittance_FT),
    )

    if gpu:
        cp.cuda.runtime.deviceSynchronize()

    host_params_h_transmittance = irfft(host_params_h_transmittance_FT).astype(float32)

    if gpu:
        cp.cuda.runtime.deviceSynchronize()

    transmittance_h = asnumpy(host_params_h_transmittance)[: init_params_h.N_v]

    if verbose_gpu >= 2:
        print("done!")

    if verbose_gpu == 1:
        print("[rG = {0}%".format((np.exp(iter_params_h.log_dwG) - 1) * 100))
        print("rL = {0}%]".format((np.exp(iter_params_h.log_dwL) - 1) * 100))

        print("Finished calculating spectrum!")

    return abscoeff_h, transmittance_h

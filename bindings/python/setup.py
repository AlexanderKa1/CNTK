import sys
import os
import shutil
from glob import glob
import platform
from warnings import warn
from setuptools import setup, Extension, find_packages
import numpy
import re

IS_WINDOWS = platform.system() == 'Windows'

IS_PY2 = sys.version_info.major == 2

# TODO should handle swig path specified via build_ext --swig-path
if os.system('swig -version 1>%s 2>%s' % (os.devnull, os.devnull)) != 0:
    print("Please install swig (>= 3.0.10) and include it in your path.\n")
    sys.exit(1)

if IS_WINDOWS:
    if os.system('cl 1>%s 2>%s' % (os.devnull, os.devnull)) != 0:
        print("Compiler was not found in path.\n"
              "Make sure you installed the C++ tools during Visual Studio 2017 install and \n"
              "run vcvarsall.bat from a DOS command prompt:\n"
              "  \"C:\\Program Files (x86)\\Microsoft Visual Studio\\17\\Community\\VC\\Auxiliary\\Build\\vcvarsall\" amd64 -vcvars_ver=14.11\n")
        sys.exit(1)

    try:
        assert(os.environ["MSSdk"] == "1");
        assert(os.environ["DISTUTILS_USE_SDK"] == "1");
    except (KeyError, AssertionError) as e:
        print("Please set the environment variables MSSdk and DISTUTILS_USE_SDK to 1:\n"
              "  set MSSdk=1\n"
              "  set DISTUTILS_USE_SDK=1\n")
        sys.exit(1)

CNTK_PATH = os.path.join(os.path.dirname(__file__), "..", "..")
CNTK_SOURCE_PATH = os.path.join(CNTK_PATH, "Source")
PROJ_LIB_PATH = os.path.join(os.path.dirname(__file__), "cntk", "libs")

if 'CNTK_LIB_PATH' in os.environ:
    CNTK_LIB_PATH = os.environ['CNTK_LIB_PATH']
else:
    # Assumes GPU SKU is being built
    if IS_WINDOWS:
        CNTK_LIB_PATH = os.path.join(CNTK_PATH, "x64", "Release")
    else:
        CNTK_LIB_PATH = os.path.join(
            CNTK_PATH, "build", "gpu", "release", "lib")

print("Using CNTK sources at '%s'" % os.path.abspath(CNTK_SOURCE_PATH))
print("Using CNTK libs at '%s'" % os.path.abspath(CNTK_LIB_PATH))


def lib_path(fn):
    return os.path.normpath(os.path.join(CNTK_LIB_PATH, fn))


def proj_lib_path(fn):
    return os.path.normpath(os.path.join(PROJ_LIB_PATH, fn))


def strip_path(fn):
    return os.path.split(fn)[1]


def strip_ext(fn):
    return os.path.splitext(fn)[0]

if IS_WINDOWS:
    libname_rt_ext = '.dll'
    cntkLibraryName = "Cntk.Core-" + os.environ['CNTK_COMPONENT_VERSION']
    link_libs = [cntkLibraryName]
else:
    cntkLibraryName = "Cntk.Core-" + os.environ['CNTK_COMPONENT_VERSION']
    link_libs = [cntkLibraryName]
    libname_rt_ext = '.so'


if 'CNTK_LIBRARIES' in os.environ:
  rt_libs_all = [strip_path(fn) for fn in os.environ['CNTK_LIBRARIES'].split(';' if IS_WINDOWS else None)]
else:
  rt_libs_all = [strip_path(fn) for fn in glob(os.path.join(CNTK_LIB_PATH,
                                                        '*' + libname_rt_ext))]

# Filtering out undesired libs
#     We are using REGEX instead of GLOBs to perform accurate deletions
rt_libs = []
EXCLUDE_RT_LIBS = []
EXCLUDE_RT_LIBS_SUFFIX = ""
if not "--with-deps" in sys.argv or "--without-deps" in sys.argv:
    if IS_WINDOWS:
        EXCLUDE_RT_LIBS_SUFFIX = "[0-9_\-\.]*\.dll$" # Match specific DLLs listed below
        EXCLUDE_RT_LIBS += ["cublas", "cudart", "curand", "cusparse"] # Cuda
        EXCLUDE_RT_LIBS += ["cudnn"] # CUDNN
        EXCLUDE_RT_LIBS += ["opencv_world"] # OpenCV
        EXCLUDE_RT_LIBS += ["mkldnn", "mklml", "libiomp5md"] # MKL + MKL-DNN
        EXCLUDE_RT_LIBS += ["nvml"] # NVML (Nvidia driver)
    else:
        EXCLUDE_RT_LIBS_SUFFIX = ".so[0-9\.]*"
        EXCLUDE_RT_LIBS += ["libcudart", "libcublas", "libcurand", "libcusparse", "libcuda", "libnvidia-ml"] # CUDA
        EXCLUDE_RT_LIBS += ["libcudnn"] # CUDNN
        EXCLUDE_RT_LIBS += ["libopencv_core", "libopencv_imgproc", "libopencv_imgcodecs"] # OpenCV
        EXCLUDE_RT_LIBS += ["libmklml_intel", "libiomp5" "libmkldnn"] # MKL
        EXCLUDE_RT_LIBS += ["libnccl"] # NCCL

for fn in rt_libs_all:
    exclude=False
    for s in EXCLUDE_RT_LIBS:
        pattern = re.compile("%s%s" % (s, EXCLUDE_RT_LIBS_SUFFIX), re.IGNORECASE)
        if pattern.match(fn):
            exclude=True
            break
    if not exclude:
        rt_libs.append(fn)

# copy over the libraries to the cntk base directory so that the rpath is
# correctly set
if os.path.exists(PROJ_LIB_PATH):
    shutil.rmtree(PROJ_LIB_PATH)

os.mkdir(PROJ_LIB_PATH)

for fn in rt_libs:
    src_file = lib_path(fn)
    tgt_file = proj_lib_path(fn)
    os.system('strip -s %s -o %s' % (src_file, tgt_file))

if 'CNTK_EXTRA_LIBRARIES' in os.environ:
    for lib in os.environ['CNTK_EXTRA_LIBRARIES'].split():
        os.system('strip -s %s -o %s' % (lib, os.path.join(PROJ_LIB_PATH, lib)))
        rt_libs.append(strip_path(lib))

# For package_data we need to have names relative to the cntk module.
rt_libs = [os.path.join('libs', fn) for fn in rt_libs]

extra_compile_args = [
    "-DSWIG",
    "-DUNICODE"
]

if IS_WINDOWS:
    extra_compile_args += [
        "/EHsc",
        "/DEBUG:NONE",
        "/Zi",
        "/WX"
    ]
    extra_link_args = ['/DEBUG:NONE']
    runtime_library_dirs = []
else:
    extra_compile_args += [
        '--std=c++11',
    ]
    extra_link_args = []

    # Expecting the dependent libs (libcntklibrary-2.4.so, etc.) inside
    # site-packages/cntk/libs.
    runtime_library_dirs = ['$ORIGIN/cntk/libs']
    os.environ["CXX"] = "mpic++"

cntkV2LibraryInclude = os.path.join(CNTK_SOURCE_PATH, "CNTKv2LibraryDll", "API")
cntkBindingCommon = os.path.join(CNTK_PATH, "bindings", "common")

cntk_module = Extension(
    name="_cntk_py",

    sources = [os.path.join("cntk", "cntk_py.i")],
    swig_opts = ["-c++", "-D_MSC_VER", "-I" + cntkV2LibraryInclude, "-I" + cntkBindingCommon, "-Werror", "-threads" ],
    libraries = link_libs,
    library_dirs = [CNTK_LIB_PATH],

    runtime_library_dirs = runtime_library_dirs,

    include_dirs = [
        cntkV2LibraryInclude,
        os.path.join(CNTK_SOURCE_PATH, "Math"),
        os.path.join(CNTK_SOURCE_PATH, "Common", "Include"),
        numpy.get_include(),
    ],

    extra_compile_args=extra_compile_args,
    extra_link_args=extra_link_args,
    language="c++",
    depends = [os.path.join(CNTK_SOURCE_PATH, "Common", "Include", "ExceptionWithCallStack.h")] +
        [os.path.join(cntkBindingCommon, f) for f in ["CNTKExceptionHandling.i", "CNTKValueExtend.i", "CNTKWarnFilters.i"]] +
        [os.path.join(cntkV2LibraryInclude, f) for f in ["CNTKLibraryInternals.h", "CNTKLibrary.h"]],
)

# Do not include examples
packages = [x for x in find_packages() if x.startswith('cntk') and not x.startswith('cntk.swig')]

package_data = { 'cntk': ['pytest.ini', 'io/tests/tf_data.txt', 'contrib/deeprl/tests/data/initial_policy_network.dnn'] }
package_data['cntk'] += rt_libs
kwargs = dict(package_data = package_data)

cntk_install_requires = [
    'numpy>=1.11',
    'scipy>=0.17'
]

if IS_PY2:
    cntk_install_requires.append('enum34>=1.1.6')

setup(name="cntk",
      version="2.4",
      url="http://cntk.ai",
      ext_modules=[cntk_module],
      packages=packages,
      install_requires=cntk_install_requires,
      **kwargs)

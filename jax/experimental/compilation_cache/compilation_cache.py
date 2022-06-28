# Copyright 2021 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import hashlib
import jax
from jax.experimental.compilation_cache.file_system_cache import FileSystemCache
from jax.lib import xla_client
from typing import Optional

_cache = None

def initialize_cache(path, max_cache_size_bytes=32 * 2**30):
    """Creates a global cache object. Should only be called once per process.

       max_cache_sixe defaults to 32GiB.
    """
    global _cache
    assert _cache == None, f"The cache path has already been initialized to {_cache}"
    _cache = FileSystemCache(path, max_cache_size_bytes)

def get_executable(xla_computation, compile_options) -> Optional[xla_client.Executable]:
    """Returns the cached executable if present, or None otherwise."""
    assert _cache is not None, "initialize_cache must be called before you can call get_executable()"
    cache_key = get_cache_key(xla_computation, compile_options)
    xla_executable_serialized = _cache.get(cache_key)
    if not xla_executable_serialized:
        return None
    backend = jax.lib.xla_bridge.get_backend()
    # TODO(skye): xla_computation.get_hlo_module() is the unoptimized HLO but it should
     #be optimized
    xla_executable_deserialized = backend.deserialize_executable(
                                  xla_executable_serialized,
                                  xla_computation.get_hlo_module(),
                                  compile_options)
    return xla_executable_deserialized

def put_executable(xla_computation, compile_options, executable: xla_client.Executable):
    """Adds 'executable' to the cache, possibly evicting older entries."""
    assert _cache is not None, "initialize_cache must be called before you can call put_executable()"
    cache_key = get_cache_key(xla_computation, compile_options)
    backend = jax.lib.xla_bridge.get_backend()
    serialized_executable = backend.serialize_executable(executable)
    _cache.put(cache_key, serialized_executable)

def get_cache_key(xla_computation, compile_options) -> str:
    """Creates a hashed string to use as a key to the compilation cache.

       get_cache_key takes in the xla_computation and compile_options of a program and hashes
       all the components into a uniuqe byte string. This byte string is returned as a regular
       string that is 256 characters long.

       Typical return value example:

            '14ac577cdb2ef6d986078b4054cc9893a9a14a16dbb0d8f37b89167c1f1aacdf'

    """
    hash_obj = hashlib.sha256()
    hash_obj.update(xla_computation.as_serialized_hlo_module_proto())
    _hash_compile_options(hash_obj, compile_options)
    hash_obj.update(bytes(jax.lib.version))
    _hash_platform(hash_obj, jax.lib.xla_bridge.get_backend())
    return hash_obj.digest().hex()

def _hash_compile_options(hash_obj, compile_options_obj):
    assert len(dir(compile_options_obj)) == 31,(f"Unexpected number of CompileOption fields: "
            f"{len(dir(compile_options_obj))}. This likely: means that an extra "
            f"field was added, and this function needs to be updated.")

    if compile_options_obj.argument_layouts is not None:
      map(lambda shape: hash_obj.update(shape.to_serialized_proto()),
          compile_options_obj.argument_layouts)
    _hash_int(hash_obj, compile_options_obj.parameter_is_tupled_arguments)
    _hash_executable_build_options(hash_obj, compile_options_obj.executable_build_options)
    _hash_bool(hash_obj, compile_options_obj.tuple_arguments)
    _hash_int(hash_obj, compile_options_obj.num_replicas)
    _hash_int(hash_obj, compile_options_obj.num_partitions)
    if compile_options_obj.device_assignment is not None:
        hash_obj.update(compile_options_obj.device_assignment.serialize())

def _hash_executable_build_options(hash_obj, executable_obj):
    assert len(dir(executable_obj)) == 30, (f"Unexpected number of executable_build_options fields: "
            f"{len(dir(executable_obj))}. This likely means that an extra "
            f"field was added, and this function needs to be updated.")
    if executable_obj.result_layout is not None:
      hash_obj.update(executable_obj.result_layout.to_serialized_proto())
    _hash_int(hash_obj, executable_obj.num_replicas)
    _hash_int(hash_obj, executable_obj.num_partitions)
    _hash_debug_options(hash_obj, executable_obj.debug_options)
    if executable_obj.device_assignment is not None:
        hash_obj.update(executable_obj.device_assignment.serialize())
    _hash_bool(hash_obj, executable_obj.use_spmd_partitioning)

def _hash_debug_options(hash_obj, debug_obj):
    _hash_bool(hash_obj, debug_obj.xla_cpu_enable_fast_math)
    _hash_bool(hash_obj, debug_obj.xla_cpu_fast_math_honor_infs)
    _hash_bool(hash_obj, debug_obj.xla_cpu_fast_math_honor_nans)
    _hash_bool(hash_obj, debug_obj.xla_cpu_fast_math_honor_division)
    _hash_bool(hash_obj, debug_obj.xla_cpu_fast_math_honor_functions)
    _hash_bool(hash_obj, debug_obj.xla_gpu_enable_fast_min_max)
    _hash_int(hash_obj, debug_obj.xla_backend_optimization_level)
    _hash_bool(hash_obj, debug_obj.xla_cpu_enable_xprof_traceme)
    _hash_bool(hash_obj, debug_obj.xla_llvm_disable_expensive_passes)
    _hash_bool(hash_obj, debug_obj.xla_test_all_input_layouts)

def _hash_platform(hash_obj, backend):
    _hash_string(hash_obj, backend.platform)
    _hash_string(hash_obj, backend.platform_version)
    _hash_string(hash_obj, backend.runtime_type)

def _hash_int(hash_obj, int_var):
    hash_obj.update(int_var.to_bytes(8, byteorder='big'))

def _hash_bool(hash_obj, bool_var):
    hash_obj.update(bool_var.to_bytes(1, byteorder='big'))

def _hash_string(hash_obj, str_var):
    hash_obj.update(str_var.encode('utf-8').strip())

def is_initialized():
    return _cache is not None

# Description:
# Python APIs for various Tensorflow backends.

load("//tensorflow:tensorflow.bzl", "if_windows")

package(
    default_visibility = ["//visibility:public"],
    licenses = ["notice"],
)

py_library(
    name = "compiler",
    srcs = ["__init__.py"],
    srcs_version = "PY3",
    deps = if_windows(
        ["//tensorflow/python/compiler/tensorrt:trt_convert_windows"],
        otherwise = ["//tensorflow/python/compiler/tensorrt:init_py"],
    ) + [
        "//tensorflow/python/compiler/mlir",
        "//tensorflow/python/compiler/xla:compiler_py",
    ],
)

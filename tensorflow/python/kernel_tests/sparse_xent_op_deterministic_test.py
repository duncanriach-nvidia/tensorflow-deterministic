# Copyright 2021 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Tests for deterministic functionality of SparseSoftmaxCrossEntropyWithLogits op."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os

import numpy as np

from tensorflow.python.eager import backprop
from tensorflow.python.framework import constant_op
from tensorflow.python.framework import dtypes
from tensorflow.python.framework import errors_impl
from tensorflow.python.framework import test_util
from tensorflow.python.kernel_tests import sparse_xent_op_test_base
# The following import is required to register the gradient function.
from tensorflow.python.ops.nn_grad import _SparseSoftmaxCrossEntropyWithLogitsGrad  # pylint: disable=unused-import
from tensorflow.python.ops import gen_nn_ops
from tensorflow.python.ops import nn_ops
from tensorflow.python.platform import test


class SparseXentOpDeterminismExceptionsTest(test.TestCase):
  """Test d9m-unimplemented exceptions from SparseSoftmaxXentWithLogitsOp.

  Test that tf.errors.UnimplementedError is thrown, as
  appropriate, by the GPU code-paths through SparseSoftmaxXentWithLogitsOp when
  deterministic ops are enabled.

  This test assumes that sparse_xent_op_test.py runs equivalent test cases
  when deterministic ops are not enabled and will therefore detect erroneous
  exception throwing in those cases.
  """

  @test_util.run_gpu_only
  @test_util.run_in_graph_and_eager_modes
  def testExceptionThrowing(self):
    with self.session(), test_util.force_gpu():
      for features_dtype in [dtypes.float16, dtypes.float32]:
        for labels_dtype in [dtypes.int32, dtypes.int64]:
          features = constant_op.constant([[0.3, 0.5], [0.2, 0.6]],
                                          dtype=features_dtype)
          labels = constant_op.constant([1, 0], dtype=labels_dtype)
          with self.assertRaisesRegex(
              errors_impl.UnimplementedError,
              "The GPU implementation of SparseSoftmaxCrossEntropyWithLogits " +
              "that would have been executed is not deterministic. Note that " +
              "the Python API uses an alternative, deterministic, " +
              "GPU-accelerated path when determinsim is enabled."):
            result = gen_nn_ops.sparse_softmax_cross_entropy_with_logits(
                features=features, labels=labels)
            self.evaluate(result)


class SparseXentOpDeterministicTest(
    sparse_xent_op_test_base.SparseXentOpTestBase):
  """Test that SparseSoftmaxCrossEntropyWithLogits operates reproducibly.

  Inheriting from sparse_xent_op_test_base.SparseXentOpTestBase ensures that
  regular op functionality is correct when the deterministic code-path is
  selected.

  Note that because nn_ops.sparse_softmax_cross_entropy_with_logits_v2 calls
  nn_ops.sparse_softmax_cross_entropy_with_logits directly, the focus of
  testing is on the former in order to test both.
  """

  def _randomInts(self, shape, high, dtype):
    return constant_op.constant(
        np.random.randint(low=0, high=high, size=shape).astype(dtype))

  def _randomFloats(self, shape, dtype):
    return constant_op.constant(
        (2 * np.random.random_sample(shape) - 1).astype(dtype))

  def _generateInputs(self, labels_dtype, logits_dtype, seed):
    batch_size = 1024
    classes_count = 1000
    np.random.seed(seed)
    labels_shape = (batch_size)
    labels = self._randomInts(
        labels_shape, high=classes_count, dtype=labels_dtype)
    logits_shape = (batch_size, classes_count)
    logits = self._randomFloats(logits_shape, logits_dtype)
    return labels, logits

  @test_util.run_in_graph_and_eager_modes
  def testForward(self):
    with self.cached_session():
      for logits_dtype in [np.float16, np.float32, np.float64]:
        for labels_dtype in [np.int32, np.int64]:
          for trial in range(5):
            seed = 123 + trial
            labels, logits = self._generateInputs(
                labels_dtype, logits_dtype, seed=seed)
            result_a = nn_ops.sparse_softmax_cross_entropy_with_logits_v2(
                labels=labels, logits=logits)
            result_b = nn_ops.sparse_softmax_cross_entropy_with_logits_v2(
                labels=labels, logits=logits)
            self.assertAllEqual(result_a, result_b)

  @test_util.run_in_graph_and_eager_modes
  def testBackward(self):
    with self.cached_session():
      for logits_dtype in [np.float16, np.float32, np.float64]:
        for labels_dtype in [np.int32, np.int64]:
          labels, logits = self._generateInputs(
              labels_dtype, logits_dtype, seed=456)
          output_shape = labels.shape[0]

          def gradients(seed):
            np.random.seed(seed)
            upstream_gradients = self._randomFloats(output_shape, logits_dtype)
            with backprop.GradientTape(persistent=True) as tape:
              tape.watch(logits)
              op_output = nn_ops.sparse_softmax_cross_entropy_with_logits_v2(
                  labels=labels, logits=logits)
              gradient_injector_output = op_output * upstream_gradients
            return tape.gradient(gradient_injector_output, logits)

          for trial in range(5):
            seed = 456 + trial
            result_a = gradients(seed=seed)
            result_b = gradients(seed=seed)
            self.assertAllEqual(result_a, result_b)

  # Modifications to the parent class
  # (sparse_xent_op_test_base.SparseXentOpTestBase) follow

  def testInvalidLabelNans(self):
    """Modified test for invalid label NaNs.

    The pre-existing, nondeterministic implementation throws an exception when
    any of the label values are invalid (less than zero or greater than the
    number of classes minus one) when running on CPU but introduces NaNs when
    running on GPU. The deterministic implementation introduces NaNs on both CPU
    and GPU.
    """
    self._testInvalidLabelNans()

  def testInvalidLabelException(self):
    """Modified test for invalid label exception.

    The pre-existing, nondeterministic implementation throws an exception when
    any of the label values are invalid (less than zero or greater than the
    number of classes minus one) when running on CPU but introduces NaNs when
    running on GPU. The deterministic implementation introduces NaNs on both CPU
    and GPU.
    """
    pass

  def testLabelsPlaceholderScalar(self):
    """Test exception-throwing for non-statically-shaped, zero-rank labels.

    The deterministic implementation cannot check for this case because it does
    not have a specific implementation of SparseSoftmaxXentWithLogitsOp.
    Instead tf.gather, which is used to create the deterministic implementation,
    throws an error.
    """
    self._testLabelsPlaceholderScalar(
        expected_error_message="Expected batch_dims in the range \[0, 0\], " +
                               "but got 1")

  def testScalarHandling(self):
    """Test exception-throwing for non-statically-shaped, zero-rank labels.

    The deterministic implementation cannot check for this case because it does
    not have a specific implementation of SparseSoftmaxXentWithLogitsOp.
    Instead tf.gather, which is used to create the deterministic implementation,
    throws an error.
    """
    self._testScalarHandling(
        expected_regex="Expected batch_dims in the range \[0, 0\], but got 1.*")


if __name__ == "__main__":
  # Note that the effect of setting the following environment variable to
  # 'true' is not tested. Unless we can find a simpler pattern for testing these
  # environment variables, it would require this file to be made into a base
  # and then two more test files to be created.
  os.environ["TF_DETERMINISTIC_OPS"] = "1"
  # The following instruction is to be deleted after
  # tf.math.unsorted_segment_sum operates deterministically in top-of-tree (and
  # therefore doesn't throw d9m-unimplemented exceptions), and before the
  # current PR is merged.
  os.environ["TF_DISABLE_SEGMENT_REDUCTION_OP_DETERMINISM_EXCEPTIONS"] = "1"
  test.main()

# coding: utf-8
"""Frontend collection for tree-lite"""
from __future__ import absolute_import
from .core import _LIB, c_str, c_array, _check_call, TreeliteError
from .compat import STRING_TYPES
import ctypes
import collections

def _isascii(string):
  """Tests if a given string is pure ASCII; works for both Python 2 and 3"""
  try:
    return (len(string) == len(string.encode()))
  except UnicodeDecodeError:
    return False
  except UnicodeEncodeError:
    return False

class Model(object):
  """Decision tree ensemble model"""
  def __init__(self, handle=None):
    """
    Decision tree ensemble model

    Parameters
    ----------
    handle : `ctypes.c_void_p`, optional
        Initial value of model handle
    """
    if handle is None:
      self.handle = None
    else:
      if not isinstance(handle, ctypes.c_void_p):
        raise ValueError('Model handle must be of type ctypes.c_void_p')
      self.handle = handle

  def __del__(self):
    if self.handle is not None:
      _check_call(_LIB.TreelitePredictorFree(self.handle))
      self.handle = None

def load_model_from_file(filename, format):
  """
  Loads a tree ensemble model from a file.

  Parameters
  ----------
  filename : string
      path to model file
  format : string
      model file format

  Returns
  -------
  model : `Model` object
      loaded model
  """
  if not _isascii(format):
    raise ValueError('format parameter must be an ASCII string')
  format = format.lower()
  handle = ctypes.c_void_p()
  if format == 'lightgbm':
    _check_call(_LIB.TreeliteLoadLightGBMModel(c_str(filename),
                                               ctypes.byref(handle)))
  elif format == 'xgboost':
    _check_call(_LIB.TreeliteLoadXGBoostModel(c_str(filename),
                                              ctypes.byref(handle)))
  elif format == 'protobuf':
    _check_call(_LIB.TreeliteLoadProtobufModel(c_str(filename),
                                               ctypes.byref(handle)))
  else:
    raise ValueError('Unknown format: must be one of ' \
                     + '{lightgbm, xgboost, protobuf}')
  model = Model(handle)
  return model

class ModelBuilder(object):
  """
  Builder class for tree ensemble model: provides tools to iteratively build
  an ensemble of decision trees
  """
  class Node(object):
    """Handle to a node in a tree"""
    def __init__(self):
      self.empty = True

    def set_root(self):
      """
      Set the node as the root

      Returns
      -------
      self (for method chaining)
      """
      try:
        _check_call(_LIB.TreeliteTreeBuilderSetRootNode(self.tree.handle,
                                                  ctypes.c_int(self.node_key)))
        return self
      except AttributeError:
        raise TreeliteError('This node has never been inserted into a tree; '\
                           + 'a node must be inserted before it can be a root')

    def set_leaf_node(self, leaf_value):
      """
      Set the node as a leaf node

      Parameters
      ----------
      leaf_value : float / list of float
          Usually a single leaf value (weight) of the leaf node
          For multiclass random forest classifier, leaf_value should be a list
          of leaf weights
      
      Returns
      -------
      self (for method chaining)
      """
      # check if leaf_value is a list-like object
      try:
        iterator = iter(leaf_value)
        is_list = True
      except TypeError:
        is_list = False

      try:
        if is_list:
          leaf_value = [float(i) for i in leaf_value]
        else:
          leaf_value = float(leaf_value)
      except TypeError:
        raise TreeliteError('leaf_value parameter should be either a ' + \
                            'single float or a list of floats')

      try:
        if is_list:
          _check_call(_LIB.TreeliteTreeBuilderSetLeafVectorNode(
                                                   self.tree.handle,
                                                   ctypes.c_int(self.node_key),
                                          c_array(ctypes.c_float, leaf_value),
                                             ctypes.c_size_t(len(leaf_value))))
        else:
          _check_call(_LIB.TreeliteTreeBuilderSetLeafNode(
                                                   self.tree.handle,
                                                   ctypes.c_int(self.node_key),
                                                   ctypes.c_float(leaf_value)))
        self.empty = False
        return self
      except AttributeError:
        raise TreeliteError('This node has never been inserted into a tree; '\
                      + 'a node must be inserted before it can be a leaf node')
  
    def set_numerical_test_node(self, feature_id, opname, threshold,
                                default_left, left_child_key, right_child_key):
      """
      Set the node as a test node with numerical split. The test is in the form
      [feature value] OP [threshold]. Depending on the result of the test,
      either left or right child would be taken.

      Parameters
      ----------
      feature_id : int
          feature index
      opname : string
          binary operator to use in the test
      threshold : float
          threshold value
      default_left : boolean
          default direction for missing values (True for left; False for right)
      left_child_key : int
          unique integer key to identify the left child node
      right_child_key : int
          unique integer key to identify the right child node
  
      Returns
      -------
      self (for method chaining)
      """
      try:
        # automatically create child nodes that don't exist yet
        if left_child_key not in self.tree:
          self.tree[left_child_key] = ModelBuilder.Node()
        if right_child_key not in self.tree:
          self.tree[right_child_key] = ModelBuilder.Node()
        _check_call(_LIB.TreeliteTreeBuilderSetNumericalTestNode(
                                 self.tree.handle, ctypes.c_int(self.node_key),
                                 ctypes.c_uint(feature_id), c_str(opname),
                                 ctypes.c_float(threshold),
                                 ctypes.c_int(1 if default_left else 0),
                                 ctypes.c_int(left_child_key),
                                 ctypes.c_int(right_child_key)))
        self.empty = False
        return self
      except AttributeError:
        raise TreeliteError('This node has never been inserted into a tree; '\
                      + 'a node must be inserted before it can be a test node')

    def set_categorical_test_node(self, feature_id, left_categories,
                                  default_left, left_child_key,
                                  right_child_key):
      """
      Set the node as a test node with categorical split. A list defines all
      categories that would be classified as the left side. Categories are
      integers ranging from 0 to (n-1), where n is the number of categories in
      that particular feature. Let's assume n <= 64.

      Parameters
      ----------
      feature_id : int
          feature index
      left_categories : list of int, with every element not exceeding 63
          list of categories belonging to the left child.
      default_left : boolean
          default direction for missing values (True for left; False for right)
      left_child_key : int
          unique integer key to identify the left child node
      right_child_key : int
          unique integer key to identify the right child node

      Returns
      -------
      self (for method chaining)
      """
      try:
        # automatically create child nodes that don't exist yet
        if left_child_key not in self.tree:
          self.tree[left_child_key] = ModelBuilder.Node()
        if right_child_key not in self.tree:
          self.tree[right_child_key] = ModelBuilder.Node()
        _check_call(_LIB.TreeliteTreeBuilderSetCategoricalTestNode(
                                 self.tree.handle, ctypes.c_int(self.node_key),
                                 ctypes.c_uint(feature_id),
                                 c_array(ctypes.c_ubyte, left_categories),
                                 ctypes.c_size_t(len(left_categories)),
                                 ctypes.c_int(1 if default_left else 0),
                                 ctypes.c_int(left_child_key),
                                 ctypes.c_int(right_child_key)))
        self.empty = False
        return self
      except AttributeError:
        raise TreeliteError('This node has never been inserted into a tree; '\
                      + 'a node must be inserted before it can be a test node')

  class Tree(object):
    """Handle to a decision tree in a tree ensemble Builder"""
    def __init__(self):
      self.handle = ctypes.c_void_p()
      _check_call(_LIB.TreeliteCreateTreeBuilder(ctypes.byref(self.handle)))
      self.nodes = {}

    def __del__(self):
      if self.handle is not None:
        if not hasattr(self, 'ensemble'):
          # need a separate deletion if tree is not part of an ensemble
          _check_call(_LIB.TreeliteDeleteTreeBuilder(self.handle))
        self.handle = None

    """Implement dict semantics whenever applicable"""
    def items(self):
      return self.nodes.items()

    def keys(self):
      return self.nodes.keys()

    def values(self):
      return self.nodes.values()

    def __len__(self):
      return len(self.nodes)

    def __getitem__(self, key):
      if key not in self.nodes:
        # implicitly create a new node
        self.__setitem__(key, ModelBuilder.Node())
      return self.nodes.__getitem__(key)

    def __setitem__(self, key, value):
      if not isinstance(value, ModelBuilder.Node):
        raise ValueError('Value must be of type ModelBuidler.Node')
      if key in self.nodes:
        raise KeyError('Nodes with duplicate keys are not allowed. ' + \
                       'If you meant to replace node {}, '.format(key) + \
                       'delete it first and then add an empty node with ' + \
                       'the same key.')
      if not value.empty:
        raise ValueError('Can only insert an empty node')
      _check_call(_LIB.TreeliteTreeBuilderCreateNode(self.handle,
                                                     ctypes.c_int(key)))
      self.nodes.__setitem__(key, value)
      value.node_key = key  # save node id for later
      value.tree = self

    def __delitem__(self, key):
      self.nodes.__delitem__(key)

    def __iter__(self):
      return self.nodes.__iter__()

    def __reversed__(self):
      return self.nodes.__reversed__()

  def __init__(self, num_feature, num_output_group=1, params={}):
    """
    Builder class for tree ensemble model

    Parameters
    ----------
    num_feature : integer
        number of features used in model being built. We assume that all
        feature indices are between 0 and (num_feature - 1)
    num_output_group : integer, optional (defaults to 1)
        number of output groups; >1 indicates multiclass classification
    params : dict, optional (defaults to {})
        parameters to be used with the resulting model
    """
    if not isinstance(num_feature, int):
      raise ValueError('num_feature must be of int type')
    if num_feature <= 0:
      raise ValueError('num_feature must be strictly positive')
    if not isinstance(num_output_group, int):
      raise ValueError('num_output_group must be of int type')
    if num_output_group <= 0:
      raise ValueError('num_output_group must be strictly positive')
    self.handle = ctypes.c_void_p()
    _check_call(_LIB.TreeliteCreateModelBuilder(ctypes.c_int(num_feature),
                                                ctypes.c_int(num_output_group),
                                                ctypes.byref(self.handle)))
    _params = dict(params) if isinstance(params, list) else params
    self._set_param(_params or {})
    self.trees = []

  def insert(self, tree, index):
    """
    Insert a tree at specified location in the ensemble

    Parameters
    ----------
    tree : `ModelBuilder.Tree` object
        tree to be inserted
    index : integer
        index of the element before which to insert the tree
    """
    if not isinstance(index, int):
      raise ValueError('index must be of int type')
    if index < 0 or index > len(self):
      raise ValueError('index out of bounds')
    if not isinstance(tree, ModelBuilder.Tree):
      raise ValueError('tree must be of type ModelBuilder.Tree')
    ret = _LIB.TreeliteModelBuilderInsertTree(self.handle,
                                              tree.handle,
                                              ctypes.c_int(index))
    _check_call(0 if ret == index else -1)
    if ret != index:
      raise ValueError('Somehow tree got inserted at wrong location')
    # delete the stale handle to the inserted tree and get a new one
    _check_call(_LIB.TreeliteDeleteTreeBuilder(tree.handle))
    _check_call(_LIB.TreeliteModelBuilderGetTree(self.handle,
                                                 ctypes.c_int(index),
                                                 ctypes.byref(tree.handle)))
    tree.ensemble = self
    self.trees.insert(index, tree)

  def append(self, tree):
    """
    Add a tree at the end of the ensemble

    Parameters
    ----------
    tree : `ModelBuilder.Tree` object
        tree to be added
    """
    self.insert(tree, len(self))

  def commit(self):
    """
    Finalize the ensemble model

    Returns
    -------
    model : `Model` object
        finished model
    """
    model_handle = ctypes.c_void_p()
    _check_call(_LIB.TreeliteModelBuilderCommitModel(self.handle,
                                                   ctypes.byref(model_handle)))
    return Model(model_handle)

  def __del__(self):
    if self.handle is not None:
      _check_call(_LIB.TreeliteDeleteModelBuilder(self.handle))
      self.handle = None

  """Implement list semantics whenever applicable"""
  def __len__(self):
    return len(self.trees)

  def __getitem__(self, index):
    return self.trees.__getitem__(index)

  def __delitem__(self, index):
    _check_call(_LIB.TreeliteModelBuilderDeleteTree(self.handle,
                                                    ctypes.c_int(index)))
    self.trees[index].handle = None  # handle is already invalid
    self.trees.__delitem__(index)

  def __iter__(self):
    return self.trees.__iter__()

  def __reversed__(self):
    return self.trees.__reversed__()

  def _set_param(self, params, value=None):
    """
    Set parameter(s)

    Parameters
    ----------
    params: dict / list / string
        list of key-alue pairs, dict or simply string key
    value: optional
        value of the specified parameter, when params is a single string
    """
    if isinstance(params, collections.Mapping):
      params = params.items()
    elif isinstance(params, STRING_TYPES) and value is not None:
      params = [(params, value)]
    for key, val in params:
      _check_call(_LIB.TreeliteModelBuilderSetModelParam(self.handle,
                                                         c_str(key),
                                                         c_str(val)))

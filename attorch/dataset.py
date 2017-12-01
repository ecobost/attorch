from collections import defaultdict, namedtuple, Mapping

import h5py
import torch
from torch.utils.data import Dataset
import numpy as np
from torch.autograd import Variable


class DataTransform:
    def initialize(self, dataset):
        pass

    def __repr__(self):
        return self.__class__.__name__


class TransformFromFuncs(DataTransform):
    def __init__(self):
        super().__init__()
        self.transformees = []

    def initialize(self, dataset):
        self._transforms = []
        for d in dataset.data_keys:
            if hasattr(dataset, d + '_transform'):
                self._transforms.append(getattr(dataset, d + '_transform'))
                self.transformees.append(d)
            else:
                self._transforms.append(lambda x: x)

    def __call__(self, item):
        return tuple(tr(it) for tr, it in zip(self._transforms, item))

    def __repr__(self):
        return "{}({})".format(self.__class__.__name__, ', '.join(self.transformees))


class ToTensor(DataTransform):
    def __call__(self, item):
        return tuple(torch.from_numpy(it) for it in item)


class Chain(DataTransform):
    def __init__(self, *transforms):
        self.transforms = transforms

    def initialize(self, dataset):
        for tr in self.transforms:
            tr.initialize(dataset)

    def __call__(self, item):
        for tr in self.transforms:
            item = tr(item)
        return item

    def __repr__(self):
        return "{}[{}]".format(self.__class__.__name__, ' -> '.join(map(repr, self.transforms)))


class H5Dataset(Dataset):
    def __init__(self, filename, *data_keys, info_name=None, transform=None):
        self.fid = h5py.File(filename, 'r')
        m = None
        for key in data_keys:
            assert key in self.fid, 'Could not find {} in file'.format(key)
            if m is None:
                m = len(self.fid[key])
            else:
                assert m == len(self.fid[key]), 'Length of datasets do not match'
        self._len = m
        self.data_keys = data_keys

        if info_name is not None:
            self.info = self.fid[info_name]

        if transform is None:
            self.transform = Chain(TransformFromFuncs(), ToTensor())
        else:
            self.transform = transform

        self.transform.initialize(self)

    def __getitem__(self, item):
        return self.transform(tuple(self.fid[d][item] for d in self.data_keys))

    def __iter__(self):
        yield from map(self.__getitem__, range(len(self)))

    def __len__(self):
        return self._len

    def __repr__(self):
        return '\n'.join(['Tensor {}: {} '.format(key, self.fid[key].shape)
                          for key in self.data_keys] + ['Transforms: ' + repr(self.transform)])


class MultiTensorDataset(Dataset):
    """Dataset wrapping data and target tensors.
    Each sample will be retrieved by indexing both tensors along the first
    dimension and converted into a the according dtype.
    
    Arguments:
        *data (numpy arrays): datasets
        data_dtype               : dtype of the tensors (for cuda conversion)
    """

    def __init__(self, *data, transform=None):
        for d in data:
            assert d.shape[0] == data[0].shape[0], 'datasets must have same first dimension'
        self.data = tuple(torch.from_numpy(d.astype(np.float32)) for d in data)
        if transform is None:
            transform = lambda x: x
        self.transform = transform

    def __getitem__(self, index):
        ret = tuple(d[index] for d in self.data)
        return self.transform(ret)

    def mean(self, axis=None):
        if axis is None:
            return tuple(d.mean() for d in self.data)
        else:
            return tuple(d.mean(axis, keepdim=True) for d in self.data)

    def __len__(self):
        return self.data[0].size(0)

    def as_variables(self, **kwargs):
        return tuple(Variable(v, **kwargs) for v in self.data)

    def cuda_(self):
        self.data = tuple(v.cuda() for v in self.data)

    def cpu_(self):
        self.data = tuple(v.cpu() for v in self.data)

    def __repr__(self):
        return '\n'.join(['Tensor {}: {}'.format(i, str(t.size())) for i, t in enumerate(self.data)])


class NumpyDataset:
    """
    Arguments:
        *data (numpy arrays): datasets
    """

    def __init__(self, *data):
        for d in data:
            assert d.shape[0] == data[0].shape[0], 'datasets must have same first dimension'
        self.data = data

    def __getitem__(self, index):
        return tuple(d[index] for d in self.data)

    def mean(self, axis=None):
        if axis is None:
            return tuple(d.mean() for d in self.data)
        else:
            return tuple(d.mean(axis) for d in self.data)

    def __len__(self):
        return self.data[0].shape(0)

    def __repr__(self):
        return '\n'.join(['Array {}: {}'.format(i, str(t.shape)) for i, t in enumerate(self.data)])


def to_variable(iter, cuda=True, filter=None, **kwargs):
    """
    Converts output of iter into Variables.
    
    Args:
        iter:       iterator that returns tuples of tensors
        cuda:       whether the elements should be loaded onto the GPU
        filter:     tuple of bools as long as the number of returned elements by iter. If filter[i] is False,
                    the element is not converted.
        **kwargs:   keyword arguments for the Variable constructor
    """
    for elem in iter:
        if filter is None:
            filter = (True,) if not isinstance(elem, (tuple, list)) else len(elem) * (True,)
        if cuda:
            yield tuple(Variable(e.cuda(), **kwargs) if f else e for f, e in zip(filter, elem))
        else:
            yield tuple(Variable(e, **kwargs) if f else e for f, e in zip(filter, elem))


class ListDataset(Dataset):
    """
    Arguments:
        *data (indexable): datasets
    """

    def __init__(self, *data, transform=None):
        self.transform = transform
        for d in data:
            assert len(d) == len(data[0]), 'datasets must have same first dimension'
        self.data = data

    def __getitem__(self, index):
        if self.transform is not None:
            return self.transform(tuple(d[index] for d in self.data))
        else:
            return tuple(d[index] for d in self.data)

    def __len__(self):
        return len(self.data)

    def __repr__(self):
        return '\n'.join(['List  {}: {}'.format(i, str(len(t))) for i, t in enumerate(self.data)])

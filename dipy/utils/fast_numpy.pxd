# cython: boundscheck=False
# cython: initializedcheck=False
# cython: wraparound=False

cimport numpy as np

from libc.stdlib cimport rand
from libc.math cimport sqrt


cdef extern from "limits.h":
    int INT_MAX

# Replaces a numpy.searchsorted(arr, number, 'right')
cdef int where_to_insert(
        np.float_t* arr,
        np.float_t number,
        int size) nogil

cdef void cumsum(
        np.float_t* arr_in,
        np.float_t* arr_out,
        int N) nogil

cdef void copy_point(
        double * a,
        double * b) nogil

cdef void scalar_muliplication_point(
        double * a,
        double scalar) nogil

cdef double random()

cdef double norm(
        double[:] v)

cdef double dot(
        double[:] v1, 
        double[:] v2)

cdef void normalize(
        double[:] v)

cdef void cross(
        double[:] out, 
        double[:] v1, 
        double[:] v2)
    
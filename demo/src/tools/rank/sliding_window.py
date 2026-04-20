from math import ceil
from typing import List

def array_eq(array_1: List[str], array_2: List[str]):
    l1 = len(array_1)
    l2 = len(array_2)

    if l1 != l2:
        return False
    
    for i in range(l1):
        if array_1[i] != array_2[i]:
            return False
    
    return True

def sliding_window(compare_func, array: List[str], window_size: int = 5, step: int = 4, k_element: int = 5):

    # Base condition for recursion to stop
    if not array or len(array) <= 1:
        return array
    
    array_copy = array.copy()
 
    # Loop 1 time through the array with window_size and step
    windows = [_ for _ in range(len(array))][-1::-step]
    iterations = ceil((len(array) - window_size) / step) + 1

    list_flag = True

    for i in range(iterations):
        end = windows[i]
        start = max(0, end-window_size+1)
        window = array[start:end+1]
        sorted_window = compare_func(window)
        if isinstance(sorted_window, list):
            for j in range(start, end+1):
                array[j] = sorted_window[j-start]
        elif isinstance(sorted_window, tuple):
            list_flag = False
            value, pos = sorted_window
            array[start+pos] = array[start]
            array[start] = value

    # The number of element in the correct place
    if list_flag:
        cut = window_size - step
    else:
        cut = 1

    # Check for k_elment in the correct order
    k_element -= cut
    if k_element <= 0 or array_eq(array_copy, array):
        return array
    
    # Recurse to sort the remaining elements
    left_array = sliding_window(compare_func ,array[cut:], window_size, step, k_element)

    # Apply the sorted order of remaining elements to the current array
    array = array[0:cut] + left_array

    return array
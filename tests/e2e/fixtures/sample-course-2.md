# Sorting Algorithms Overview

## Core Idea

Sorting algorithms arrange elements in a specific order (ascending or descending). Different algorithms have different time and space complexities, making them suitable for different scenarios.

## Bubble Sort

Bubble sort repeatedly steps through the list, compares adjacent elements, and swaps them if they are in the wrong order. The pass through the list is repeated until the list is sorted.

**Time Complexity:** O(n^2) average and worst case, O(n) best case
**Space Complexity:** O(1)

## Quick Sort

Quick sort is a divide-and-conquer algorithm. It selects a pivot element and partitions the array around the pivot, recursively sorting the sub-arrays.

**Time Complexity:** O(n log n) average, O(n^2) worst case
**Space Complexity:** O(log n)

## Merge Sort

Merge sort divides the array into halves, recursively sorts each half, and then merges the sorted halves.

**Time Complexity:** O(n log n) in all cases
**Space Complexity:** O(n)

## Practice Questions

**Q1:** Which sorting algorithm has the best average-case time complexity?
- A) Bubble Sort
- B) Selection Sort
- C) Merge Sort
- D) Insertion Sort

**Answer:** C) Merge Sort

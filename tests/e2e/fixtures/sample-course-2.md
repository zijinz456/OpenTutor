# Introduction to Sorting Algorithms

## Bubble Sort
Bubble Sort repeatedly steps through the list, compares adjacent elements, and swaps them if they are in the wrong order.

- Time complexity: O(n²)
- Space complexity: O(1)
- Stable: Yes

## Quick Sort
Quick Sort is a divide-and-conquer algorithm that selects a "pivot" element and partitions the other elements into two sub-arrays.

- Average time complexity: O(n log n)
- Worst case: O(n²)
- Space complexity: O(log n)
- Not stable

## Merge Sort
Merge Sort divides the array into halves, recursively sorts them, and then merges the sorted halves.

- Time complexity: O(n log n)
- Space complexity: O(n)
- Stable: Yes

## Comparison Table

| Algorithm | Best | Average | Worst | Space | Stable |
|-----------|------|---------|-------|-------|--------|
| Bubble    | O(n) | O(n²)   | O(n²) | O(1) | Yes    |
| Quick     | O(n log n) | O(n log n) | O(n²) | O(log n) | No |
| Merge     | O(n log n) | O(n log n) | O(n log n) | O(n) | Yes |

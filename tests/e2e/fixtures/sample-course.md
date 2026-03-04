# Binary Search Basics

## Core Idea

Binary search is an efficient algorithm for finding an item in a sorted list. It works by repeatedly dividing the search interval in half. If the target value is less than the middle element, the search continues in the lower half; otherwise, it continues in the upper half.

**Time Complexity:** O(log n)
**Space Complexity:** O(1) for iterative, O(log n) for recursive

## Why It Matters

Binary search is one of the most fundamental algorithms in computer science. It reduces the number of comparisons from O(n) in linear search to O(log n), making it essential for searching in large sorted datasets.

Real-world applications include:
- Database index lookups
- Dictionary/phonebook searches
- Finding insertion points in sorted arrays
- Git bisect for finding bugs

## How It Works

1. Start with the entire sorted array
2. Find the middle element
3. If the middle element equals the target, return its position
4. If the target is less than the middle, search the left half
5. If the target is greater than the middle, search the right half
6. Repeat until found or the search space is empty

```python
def binary_search(arr, target):
    left, right = 0, len(arr) - 1
    while left <= right:
        mid = (left + right) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1
```

## Common Pitfalls

1. **Array must be sorted** — Binary search only works on sorted arrays. Applying it to unsorted data gives incorrect results.
2. **Off-by-one errors** — The boundary conditions (left <= right vs left < right) are a common source of bugs.
3. **Integer overflow** — Computing mid = (left + right) / 2 can overflow in some languages. Use mid = left + (right - left) / 2 instead.
4. **Not handling duplicates** — When duplicates exist, you may need to find the first or last occurrence rather than any occurrence.

## Practice Questions

**Q1:** What is the time complexity of binary search?
- A) O(n)
- B) O(log n)
- C) O(n log n)
- D) O(1)

**Answer:** B) O(log n)

**Q2:** What prerequisite must be met before applying binary search?
- A) The array must be of even length
- B) The array must contain unique elements
- C) The array must be sorted
- D) The array must be stored in contiguous memory

**Answer:** C) The array must be sorted

**Q3:** In binary search, if the target is greater than the middle element, which half do you search next?
- A) Left half
- B) Right half
- C) Both halves
- D) Neither

**Answer:** B) Right half

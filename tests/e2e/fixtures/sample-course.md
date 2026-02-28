# Binary Search Basics

Binary search finds a target value inside a sorted array by repeatedly halving the search range.

## Core Idea

- Start with the left and right bounds.
- Compare the middle element to the target.
- Eliminate the half that cannot contain the target.

## Why It Matters

Binary search reduces the number of comparisons from linear growth to logarithmic growth.

## Common Pitfalls

- Using binary search on unsorted data
- Off-by-one mistakes when updating bounds
- Forgetting the loop termination condition

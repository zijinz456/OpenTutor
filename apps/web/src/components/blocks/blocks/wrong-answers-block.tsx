"use client";

import { WrongAnswersView } from "@/components/sections/practice/wrong-answers-view";
import type { BlockComponentProps } from "@/lib/block-system/registry";

export default function WrongAnswersBlock({ courseId }: BlockComponentProps) {
  return <WrongAnswersView courseId={courseId} />;
}

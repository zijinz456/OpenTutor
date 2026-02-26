"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Plus, BookOpen, Trash2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardDescription, CardFooter } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { useCourseStore } from "@/store/course";

export default function DashboardPage() {
  const router = useRouter();
  const { courses, loading, fetchCourses, addCourse, removeCourse } = useCourseStore();
  const [newName, setNewName] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);

  useEffect(() => {
    fetchCourses();
  }, [fetchCourses]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    const course = await addCourse(newName.trim());
    setNewName("");
    setDialogOpen(false);
    router.push(`/course/${course.id}`);
  };

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BookOpen className="h-6 w-6" />
          <h1 className="text-xl font-semibold">OpenTutor</h1>
        </div>

        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="h-4 w-4 mr-2" />
              New Course
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Create New Course</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 pt-4">
              <Input
                placeholder="Course name (e.g. CS 101 — Data Structures)"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleCreate()}
              />
              <Button onClick={handleCreate} className="w-full">
                Create & Upload Materials
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </header>

      <main className="max-w-5xl mx-auto p-6">
        {loading && <p className="text-muted-foreground">Loading courses...</p>}

        {!loading && courses.length === 0 && (
          <div className="text-center py-20">
            <Upload className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
            <h2 className="text-lg font-medium mb-2">No courses yet</h2>
            <p className="text-muted-foreground mb-4">
              Create a course and upload your learning materials to get started.
            </p>
            <Button onClick={() => setDialogOpen(true)}>
              <Plus className="h-4 w-4 mr-2" />
              Create Your First Course
            </Button>
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {courses.map((course) => (
            <Card
              key={course.id}
              className="cursor-pointer hover:shadow-md transition-shadow"
              onClick={() => router.push(`/course/${course.id}`)}
            >
              <CardHeader>
                <CardTitle className="text-base">{course.name}</CardTitle>
                <CardDescription>
                  {course.description || "No description"}
                </CardDescription>
              </CardHeader>
              <CardFooter className="flex justify-between">
                <span className="text-xs text-muted-foreground">
                  {new Date(course.created_at).toLocaleDateString()}
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={(e) => {
                    e.stopPropagation();
                    removeCourse(course.id);
                  }}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
      </main>
    </div>
  );
}

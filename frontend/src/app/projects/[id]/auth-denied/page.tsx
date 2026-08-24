"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";

export default function AuthDeniedPage() {
  const params = useParams<{ id: string }>();
  const projectId = params?.id;

  return (
    <div className="flex min-h-screen items-center justify-center p-8">
      <Card className="max-w-md space-y-4 text-center">
        <p className="text-5xl font-bold text-warning">403</p>
        <h1 className="text-xl font-semibold">Permission Denied</h1>
        <p className="text-sm text-text-secondary">
          You don&apos;t have the required role to view this project. Project owners can
          approve workflow gates, archive projects, and manage secrets. Contact an
          administrator to request access.
        </p>
        <div className="flex justify-center gap-2">
          {projectId && (
            <Link href={`/projects/${projectId}`}>
              <Button variant="secondary">Back to Project</Button>
            </Link>
          )}
          <Link href="/dashboard">
            <Button>Go to Dashboard</Button>
          </Link>
        </div>
      </Card>
    </div>
  );
}

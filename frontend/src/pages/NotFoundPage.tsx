import { Link } from "react-router-dom";

import { EmptyState } from "../components/ui";

export function NotFoundPage() {
  return (
    <EmptyState
      title="Page not found"
      description="The page you requested does not exist."
      action={
        <Link to="/" className="text-sm font-medium text-accent-600 hover:underline">
          Back to the dashboard
        </Link>
      }
    />
  );
}

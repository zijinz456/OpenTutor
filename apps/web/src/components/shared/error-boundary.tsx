"use client";

import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        this.props.fallback ?? (
          <div role="alert" className="flex flex-col items-center justify-center p-8 text-center gap-3 animate-fade-in">
            <p className="text-sm font-medium text-destructive">Something went wrong</p>
            <p className="text-xs text-muted-foreground max-w-sm">
              {this.state.error?.message}
            </p>
            <button
              onClick={() => this.setState({ hasError: false, error: null })}
              aria-label="Retry loading this component"
              className="text-xs text-brand hover:underline"
            >
              Try again
            </button>
          </div>
        )
      );
    }

    return this.props.children;
  }
}

import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ErrorBoundary } from './ErrorBoundary';

const ThrowingComponent: React.FC<{ shouldThrow?: boolean; message?: string }> = ({
  shouldThrow = true,
  message = 'Render explosion',
}) => {
  if (shouldThrow) {
    throw new Error(message);
  }
  return <div>Healthy content</div>;
};

describe('ErrorBoundary component', () => {
  it('renders children when no error occurs', () => {
    render(
      <ErrorBoundary>
        <div>Content is fine</div>
      </ErrorBoundary>
    );
    expect(screen.getByText('Content is fine')).toBeInTheDocument();
  });

  it('catches render error and displays full-page recovery UI', () => {
    // Suppress console.error in vitest output for expected thrown error
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});

    render(
      <ErrorBoundary>
        <ThrowingComponent />
      </ErrorBoundary>
    );

    expect(screen.getByText('Something went wrong on this page.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Dashboard' })).toBeInTheDocument();

    spy.mockRestore();
  });

  it('renders compact error fallback in compact mode', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});

    render(
      <ErrorBoundary compact>
        <ThrowingComponent message="Compact explosion" />
      </ErrorBoundary>
    );

    expect(screen.getByText('Failed to load this section')).toBeInTheDocument();
    expect(screen.getByText('Compact explosion')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try Again' })).toBeInTheDocument();

    spy.mockRestore();
  });
});

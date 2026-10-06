import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { EmptyState, ErrorBanner, StatCard, StatusBadge } from './ui';

describe('UI component primitives', () => {
  it('renders StatusBadge with formatted text', () => {
    render(<StatusBadge status="completed" />);
    expect(screen.getByText('completed')).toBeInTheDocument();
  });

  it('renders StatusBadge with custom label', () => {
    render(<StatusBadge status="paused_for_approval" label="Needs Review" />);
    expect(screen.getByText('Needs Review')).toBeInTheDocument();
  });

  it('renders StatCard with value and label', () => {
    render(<StatCard icon={null} label="Total Projects" value="42" sub="+3 this week" />);
    expect(screen.getByText('Total Projects')).toBeInTheDocument();
    expect(screen.getByText('42')).toBeInTheDocument();
    expect(screen.getByText('+3 this week')).toBeInTheDocument();
  });

  it('renders EmptyState with action', () => {
    render(
      <EmptyState
        icon={null}
        title="No items found"
        description="Try adjusting your filter"
        action={<button>Create item</button>}
      />
    );
    expect(screen.getByText('No items found')).toBeInTheDocument();
    expect(screen.getByText('Try adjusting your filter')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Create item' })).toBeInTheDocument();
  });

  it('renders ErrorBanner with error message', () => {
    render(<ErrorBanner message="Failed to load workspace" />);
    expect(screen.getByText('Failed to load workspace')).toBeInTheDocument();
  });
});

import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { LandingPage } from './LandingPage';

describe('LandingPage component', () => {
  it('renders brand heading and call to actions', () => {
    render(
      <MemoryRouter>
        <LandingPage />
      </MemoryRouter>
    );

    expect(screen.getByText('API Weaver')).toBeInTheDocument();
    expect(screen.getByText('Sign in')).toBeInTheDocument();
    expect(screen.getAllByText('Get Started').length).toBeGreaterThan(0);
    expect(screen.getByText(/Train AI agents on your workflows/i)).toBeInTheDocument();
  });
});

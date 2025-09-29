# SalConBackend

## Password Reset

This project implements a password reset feature with both backend and frontend components.

### Backend

The backend is built with Django and Django Rest Framework.

**APIs:**

*   **`POST /api/v1/user/password-reset/`**:
    *   This endpoint initiates the password reset process.
    *   It expects an `email` in the request body.
    *   If the user exists, it sends an email with a password reset link.
*   **`POST /api/v1/user/reset-password/<encoded_pk>/<token>/`**:
    *   This endpoint resets the password.
    *   It expects `password`, `confirm_password`, `encoded_pk`, and `token` in the request body.
    *   It validates the token and resets the password.

**Setup:**

1.  **Install dependencies:**
    ```bash
    pip install -r backend/requirements.txt
    ```
2.  **Configure email settings:**
    *   Update your `backend/backend/settings.py` with your email provider's settings (e.g., SMTP server, username, password).
3.  **Run migrations:**
    ```bash
    python backend/manage.py migrate
    ```
4.  **Run the development server:**
    ```bash
    python backend/manage.py runserver
    ```

### Frontend

The frontend consists of two HTML files that use JavaScript to interact with the backend APIs.

*   **`forgot-password.html`**:
    *   A form to enter an email address to receive a password reset link.
*   **`reset-password.html`**:
    *   A form to enter and confirm a new password.

**Usage:**

1.  Open `forgot-password.html` in your browser.
2.  Enter your email and submit the form.
3.  Check your email for the reset link.
4.  Open the link, which will take you to `reset-password.html`.
5.  Enter your new password and submit the form.
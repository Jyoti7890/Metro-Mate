# 🚆 Metro Mate
### Your trusted companion for smarter metro travel, ticketing, and passenger support

Metro Mate is a full-stack metro service web application designed to make metro travel easier and more organized. It brings common passenger needs into one place, such as ticket booking, station search, smart card support, travel tracking, and lost & found reporting.

The goal of this project was not just to build features, but to create a system that feels useful, practical, and close to a real-world public transport product.

## 📸 Screenshots

### Home Page
![Home Page](<screenshots/Home Page.png>)

### Login / Signup
![Login Page](<screenshots/Login Page.png>)

### Stations Page
![Stations Page](<screenshots/Station Page.png>)

### Book Ticket Page
![Book Ticket Page](<screenshots/Book Ticket.png>)

### User Dashboard
![User Dashboard](<screenshots/User Dashboard.png>)

### My Bookings Page
![My Bookings Page](<screenshots/My Bookings Page.png>)

### Smart Card Page
![Smart Card Page](<screenshots/Smart Card Page.png>)

### Lost & Found Page
![Lost and Found Page](<screenshots/Lost and Found Page.png>)

### Admin Dashboard
![Admin Dashboard](<screenshots/Admin Dashboard.png>)

## ✨ Features

- Secure user signup and login flow
- Role-based access for passenger and admin users
- Metro ticket booking with automatic fare calculation
- Station listing with crowd forecast support
- User dashboard with travel history and activity insights
- Smart card balance, recharge, and transaction view
- Nearby places page connected to station-based suggestions
- Lost & found reporting system for passengers
- Admin dashboard for managing users, stations, and support activity
- Clean frontend with shared styling and reusable layouts
- Health check and deployment-ready backend setup
- Render-ready project structure for easy hosting

## 🛠️ Tech Stack

- Frontend: HTML, CSS, JavaScript, Jinja templates
- Backend: FastAPI, Python
- Database: Supabase
- Machine Learning: Scikit-learn, Pandas, Joblib
- Authentication & Security: Session-based access control
- Deployment: Render
- Version Control: Git and GitHub

## ⚙️ How It Works

1. A user opens the app and creates an account or logs in.
2. After login, the system loads user data and available metro services.
3. The passenger can explore stations, check crowd levels, and book tickets.
4. Booking records, smart card activity, and travel details are shown in the user dashboard.
5. If a user loses an item, they can create a lost report through the app.
6. Admin users can manage station records, review users, and handle support-related tasks.
7. All major data is stored in Supabase and served through FastAPI endpoints.

## 📁 Project Structure

```text
Metro-Mate/
├── backend/
├── frontend/
│   ├── static/
│   └── templates/
├── requirements.txt
├── render.yaml
├── .env.example
└── README.md
```

## 🚀 Installation Steps

1. Clone the repository.
2. Move into the project directory.
3. Create a virtual environment.
4. Install the required packages.
5. Create a local `.env` file.
6. Add your Supabase and app secret keys.
7. Start the FastAPI application.

## 🔐 Environment Variables

Create a `.env` file in the project root and add:

```env
SUPABASE_URL=your_supabase_url
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key
APP_SESSION_SECRET=your_secret_key
```

These variables are used for:

- `SUPABASE_URL` for database connection
- `SUPABASE_SERVICE_ROLE_KEY` for backend access to Supabase
- `APP_SESSION_SECRET` for secure session handling

For local development, use `.env`.  
For production, add the same values in Render environment settings.

## ▶️ How to Run Locally

```bash
git clone <your-repository-link>
cd Metro-Mate
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Then open: `http://127.0.0.1:8000`

## 📡 API Endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/` | Open login page |
| `GET` | `/home` | Open home page |
| `GET` | `/stations` | Open station page |
| `GET` | `/api/stations` | Get station list |
| `GET` | `/predict-crowd` | Get station crowd prediction |
| `POST` | `/login` | User login |
| `POST` | `/signup` | Create account |
| `POST` | `/api/book-ticket` | Book a ticket |
| `GET` | `/user-dashboard` | Get user dashboard data |
| `GET` | `/api/dashboard/admin` | Get admin dashboard data |
| `GET` | `/health` | Health check |

## 📚 Challenges & Learnings

- One of the biggest challenges was keeping the UI simple while connecting many different modules in the backend.
- Working on both passenger and admin flows helped me understand how real applications need different access levels and route control.
- Static file handling looked easy at first, but making sure the frontend worked the same in local setup and deployment was an important learning step.
- Supabase integration taught me how much small data issues can affect the full user flow.
- Deployment preparation was a strong lesson for me. A project may work on localhost, but making it GitHub-ready and Render-ready needs extra care and clean structure.
- This project improved my confidence in full-stack thinking, not just writing code page by page.

## 🔮 Future Improvements

- Add QR-based digital ticket generation
- Add online payment gateway support
- Improve dashboard filters and chart interactions
- Add email notifications for bookings and lost item updates
- Add better mobile optimization for all screens
- Add search and filter options in admin tools
- Improve recommendation and crowd prediction logic
- Add automated tests for important flows

## ✅ Conclusion

Metro Mate is a project built with the mindset of solving a real travel problem in a simple and useful way. It shows full-stack development, system thinking, deployment readiness, and attention to user experience. It is the kind of project I would proudly include in a job portfolio because it reflects both technical skills and practical product sense.

## 👤 Project Profile

**Name:** Jyoti Gola
🔗 LinkedIn: [https://www.linkedin.com/in/jyoti-gola-67251026a/](https://www.linkedin.com/in/jyoti-gola-67251026a/)\
🔗 GitHub: [https://github.com/Jyoti7890](https://github.com/Jyoti7890)

## 📄 License

This project is licensed under the **MIT License**.  
You are free to use, modify, and showcase it with proper credit.

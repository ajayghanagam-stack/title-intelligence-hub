# Test Credentials

## Platform Admin (Logikality - manages customer accounts)
- **Email**: admin@logikality.com
- **Password**: admin123
- **Role**: Platform Admin (can create customer accounts and manage micro apps)

## Customer Account (Society Title Co - has Title Intelligence subscription)
- **Email**: admin@societytitle.com
- **Password**: admin123
- **Role**: Owner (has active Title Intelligence subscription)

## Production Application URL (AWS)
- **ALB URL**: http://title-intelligence-alb-1451612729.us-east-1.elb.amazonaws.com
- **Login Page**: http://title-intelligence-alb-1451612729.us-east-1.elb.amazonaws.com/login
- **Health Check**: http://title-intelligence-alb-1451612729.us-east-1.elb.amazonaws.com/api/v1/health

## Preview/Local Application URL (Emergent)
- **Live URL**: https://dc353579-ba3e-4338-b011-8fae44983f1e.preview.emergentagent.com
- **Login Page**: https://dc353579-ba3e-4338-b011-8fae44983f1e.preview.emergentagent.com/login

## API Endpoints
- **Health Check**: GET /api/v1/health
- **Login**: POST /api/v1/auth/login
- **Admin Accounts**: /api/v1/admin/accounts

## Notes
- Use **admin@societytitle.com** to access the Title Intelligence document processing features
- Use **admin@logikality.com** for platform admin tasks (creating new customer accounts)
- Production uses PostgreSQL (RDS) + S3 storage; Preview uses SQLite + local storage

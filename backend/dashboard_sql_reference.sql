-- Metro Mate personalized dashboard SQL reference
-- Replace :current_user_email with the authenticated user's email on the server side only.

-- 1. KPI cards
select balance
from smart_cards
where user_email = :current_user_email;

select count(*) as active_tickets
from bookings
where user_email = :current_user_email
  and status = 'active';

select count(*) as total_trips,
       coalesce(sum(total_fare), 0) as total_amount_spent,
       coalesce(sum(case when date_trunc('month', coalesce(booking_date, created_at)) = date_trunc('month', now()) then total_fare else 0 end), 0) as monthly_spend
from bookings
where user_email = :current_user_email;

select count(*) filter (where status <> 'resolved') as active_complaints,
       count(*) filter (where status = 'resolved') as resolved_complaints
from lost_items
where user_email = :current_user_email;

select total_fare as last_booking_fare,
       coalesce(booking_date, created_at) as last_travel_date
from bookings
where user_email = :current_user_email
order by coalesce(booking_date, created_at) desc
limit 1;

select from_station, count(*) as trips
from bookings
where user_email = :current_user_email
group by from_station
order by trips desc
limit 1;

select to_station, count(*) as trips
from bookings
where user_email = :current_user_email
group by to_station
order by trips desc
limit 1;

select payment_method, count(*) as usage_count
from bookings
where user_email = :current_user_email
group by payment_method
order by usage_count desc
limit 1;

select count(*) filter (where type = 'credit') as recharge_count,
       coalesce(sum(case when type = 'credit' then amount else 0 end), 0) as total_recharge_amount
from card_transactions
where user_email = :current_user_email;

select amount as last_recharge_amount,
       created_at as last_recharge_date
from card_transactions
where user_email = :current_user_email
  and type = 'credit'
order by created_at desc
limit 1;

select id,
       from_station,
       to_station,
       total_fare,
       ticket_count,
       payment_method,
       status,
       coalesce(booking_date, created_at) as booking_time
from bookings
where user_email = :current_user_email
  and status = 'active'
order by coalesce(booking_date, created_at) desc
limit 1;

-- 2. Graph queries
select date(coalesce(booking_date, created_at)) as travel_date,
       count(*) as trip_count
from bookings
where user_email = :current_user_email
  and coalesce(booking_date, created_at) >= current_date - interval '6 day'
group by travel_date
order by travel_date;

select date(coalesce(booking_date, created_at)) as spend_date,
       coalesce(sum(total_fare), 0) as spend_total
from bookings
where user_email = :current_user_email
  and coalesce(booking_date, created_at) >= current_date - interval '29 day'
group by spend_date
order by spend_date;

select from_station,
       count(*) as trip_count
from bookings
where user_email = :current_user_email
group by from_station
order by trip_count desc
limit 6;

select concat(from_station, ' -> ', to_station) as route,
       count(*) as trip_count
from bookings
where user_email = :current_user_email
group by from_station, to_station
order by trip_count desc
limit 6;

select payment_method,
       count(*) as booking_count
from bookings
where user_email = :current_user_email
group by payment_method
order by booking_count desc;

select case
           when extract(hour from coalesce(booking_date, created_at)) between 5 and 11 then 'Morning'
           when extract(hour from coalesce(booking_date, created_at)) between 12 and 16 then 'Afternoon'
           when extract(hour from coalesce(booking_date, created_at)) between 17 and 21 then 'Evening'
           else 'Night'
       end as time_of_day,
       count(*) as trip_count
from bookings
where user_email = :current_user_email
group by time_of_day
order by trip_count desc;

select date(created_at) as transaction_date,
       coalesce(sum(case when type = 'credit' then amount else 0 end), 0) as credit_total,
       coalesce(sum(case when type = 'debit' then amount else 0 end), 0) as debit_total
from card_transactions
where user_email = :current_user_email
  and created_at >= current_date - interval '29 day'
group by transaction_date
order by transaction_date;

select status,
       count(*) as complaint_count
from lost_items
where user_email = :current_user_email
group by status
order by complaint_count desc;

select case
           when extract(isodow from coalesce(booking_date, created_at)) in (6, 7) then 'Weekend'
           else 'Weekday'
       end as day_bucket,
       count(*) as trip_count
from bookings
where user_email = :current_user_email
group by day_bucket
order by day_bucket;

select case
           when total_fare <= 30 then 'Low'
           when total_fare <= 80 then 'Medium'
           else 'High'
       end as fare_bucket,
       count(*) as booking_count
from bookings
where user_email = :current_user_email
group by fare_bucket
order by booking_count desc;

-- 3. Complaints with potential matches
select li.id as complaint_id,
       li.item_name,
       li.station,
       li.status,
       li.created_at,
       m.id as match_id,
       m.match_score,
       m.status as match_status,
       fi.item_name as matched_item_name,
       fi.station as matched_station
from lost_items li
left join matches m on m.lost_item_id = li.id
left join found_items fi on fi.id = m.found_item_id
where li.user_email = :current_user_email
order by li.created_at desc, m.created_at desc;

-- =========================================================
-- Admin dashboard SQL reference
-- Admin queries are global and intentionally do not filter by user_id.
-- =========================================================

-- 1. Top KPI cards
select count(*) as total_users
from users;

select count(*) as total_bookings
from bookings;

select coalesce(sum(total_fare), 0) as total_revenue
from bookings;

select count(*) as total_complaints
from lost_items;

-- 2. Core analytics
select date(coalesce(booking_date, created_at)) as booking_date,
       count(*) as booking_count
from bookings
where coalesce(booking_date, created_at) >= current_date - interval '13 day'
group by booking_date
order by booking_date;

select to_char(date_trunc('month', coalesce(booking_date, created_at)), 'Mon YYYY') as booking_month,
       coalesce(sum(total_fare), 0) as revenue_total
from bookings
group by date_trunc('month', coalesce(booking_date, created_at))
order by date_trunc('month', coalesce(booking_date, created_at));

select station_name,
       sum(usage_count) as total_usage
from (
    select from_station as station_name, count(*) as usage_count
    from bookings
    group by from_station
    union all
    select to_station as station_name, count(*) as usage_count
    from bookings
    group by to_station
) station_usage
group by station_name
order by total_usage desc
limit 8;

select extract(hour from coalesce(booking_date, created_at)) as travel_hour,
       count(*) as booking_count
from bookings
group by travel_hour
order by travel_hour;

-- 3. User management
select id,
       full_name,
       email,
       user_type,
       coalesce(account_status, status, case when is_active = false then 'blocked' else 'active' end) as account_state,
       coalesce(last_login_at, last_login) as last_login_time
from users
order by full_name;

-- 4. Station management
select id,
       name,
       line,
       sequence,
       is_interchange,
       is_elevated,
       station_type
from stations
order by line, sequence;

-- 5. Lost & found management
select li.id as complaint_id,
       u.full_name as user_name,
       li.user_email,
       li.item_name,
       li.station,
       li.status,
       li.created_at
from lost_items li
left join users u on lower(u.email) = lower(li.user_email)
order by li.created_at desc;

-- 6. Optional smart insights
select station,
       count(*) as complaint_count
from lost_items
group by station
order by complaint_count desc
limit 6;

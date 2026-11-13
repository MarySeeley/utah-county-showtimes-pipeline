-- Which theaters currently have the most upcoming showtimes?
SELECT
    city,
    cinema_name,
    COUNT(*) AS upcoming_showtimes
FROM showtimes_current
GROUP BY city, cinema_name
ORDER BY city, upcoming_showtimes DESC;

-- Which movies have the most scheduled showings?
SELECT
    movie_title,
    COUNT(*) AS showtime_count
FROM showtimes_current
GROUP BY movie_title
ORDER BY showtime_count DESC
LIMIT 20;

-- What kinds of changes has the source reported?
SELECT
    event_type,
    COUNT(*) AS event_count
FROM showtime_changes
GROUP BY event_type
ORDER BY event_count DESC;

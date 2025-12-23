--
-- PostgreSQL database dump
--

-- Dumped from database version 17.4
-- Dumped by pg_dump version 17.4

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: dm_nonnegative_decimal; Type: DOMAIN; Schema: public; Owner: postgres
--

CREATE DOMAIN public.dm_nonnegative_decimal AS numeric(10,2)
	CONSTRAINT dm_nonnegative_decimal_check CHECK ((VALUE >= (0)::numeric));


ALTER DOMAIN public.dm_nonnegative_decimal OWNER TO postgres;

--
-- Name: dm_passport; Type: DOMAIN; Schema: public; Owner: postgres
--

CREATE DOMAIN public.dm_passport AS character varying(20) NOT NULL
	CONSTRAINT dm_passport_check CHECK (((VALUE)::text ~ '^[0-9]{4}\s?[0-9]{6}$'::text));


ALTER DOMAIN public.dm_passport OWNER TO postgres;

--
-- Name: calc_booking_totals(integer); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.calc_booking_totals(booking_id_param integer) RETURNS TABLE(nights integer, room_total numeric, services_total numeric, booking_fee numeric, prepayments_total numeric, balance numeric)
    LANGUAGE plpgsql
    AS $$
DECLARE
    price DECIMAL;
BEGIN
    SELECT rt.price INTO price
    FROM Booking b JOIN Room r ON b.room_id = r.room_id JOIN RoomType rt ON r.type_id = rt.type_id
    WHERE b.booking_id = booking_id_param;

    SELECT (b.end_date - b.start_date)::int, (b.end_date - b.start_date) * price,
           COALESCE((SELECT SUM(s.price) FROM BookingService bs JOIN Service s ON bs.service_id = s.service_id WHERE bs.booking_id = booking_id_param),0),
           b.booking_fee,
           COALESCE((SELECT SUM(c.prepayment) FROM BookingGuest bg JOIN Client c ON bg.client_id = c.client_id WHERE bg.booking_id = booking_id_param),0)
    INTO nights, room_total, services_total, booking_fee, prepayments_total
    FROM Booking b WHERE b.booking_id = booking_id_param;

    balance := prepayments_total - (room_total + COALESCE(booking_fee,0) + services_total);
    RETURN NEXT;
END;
$$;


ALTER FUNCTION public.calc_booking_totals(booking_id_param integer) OWNER TO postgres;

--
-- Name: check_booking_dates(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.check_booking_dates() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.start_date >= NEW.end_date THEN
        RAISE EXCEPTION 'Дата заезда (%) должна быть раньше даты выезда (%)', NEW.start_date, NEW.end_date;
    END IF;
    RETURN NEW;
END;
$$;


ALTER FUNCTION public.check_booking_dates() OWNER TO postgres;

--
-- Name: check_room_capacity(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.check_room_capacity() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    room_capacity INT;
    guest_count INT;
BEGIN
    -- Получаем вместимость номера через Booking
    SELECT rt.capacity INTO room_capacity
    FROM Booking b
    JOIN Room r ON b.room_id = r.room_id
    JOIN RoomType rt ON r.type_id = rt.type_id
    WHERE b.booking_id = NEW.booking_id;

    -- Считаем количество гостей в бронировании
    SELECT COUNT(*) INTO guest_count
    FROM BookingGuest
    WHERE booking_id = NEW.booking_id;

    -- Проверка вместимости
    IF guest_count > room_capacity THEN
        RAISE EXCEPTION
            'Превышена вместимость номера. Гостей: %, вместимость: %',
            guest_count, room_capacity;
    END IF;

    RETURN NEW;
END;
$$;


ALTER FUNCTION public.check_room_capacity() OWNER TO postgres;

--
-- Name: fn_calc_booking_fee(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.fn_calc_booking_fee() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    nightly_price DECIMAL(10,2);
    nights INT;
BEGIN
    -- получить цену номера
    SELECT rt.price INTO nightly_price
    FROM Room r JOIN RoomType rt ON r.type_id = rt.type_id
    WHERE r.room_id = NEW.room_id;

    IF nightly_price IS NULL THEN
        RAISE EXCEPTION 'Room id % not found for fee calculation', NEW.room_id;
    END IF;

    nights := (NEW.end_date - NEW.start_date);
    IF nights <= 0 THEN
        RAISE EXCEPTION 'Неверные даты: nights=%', nights;
    END IF;

    NEW.booking_fee := ROUND((0.5 * nightly_price * nights)::numeric, 2);
    RETURN NEW;
END;
$$;


ALTER FUNCTION public.fn_calc_booking_fee() OWNER TO postgres;

--
-- Name: fn_check_booking_dates(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.fn_check_booking_dates() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.start_date >= NEW.end_date THEN
        RAISE EXCEPTION 'Дата заезда (%) должна быть строго раньше даты выезда (%)', NEW.start_date, NEW.end_date;
    END IF;
    RETURN NEW;
END;
$$;


ALTER FUNCTION public.fn_check_booking_dates() OWNER TO postgres;

--
-- Name: fn_check_booking_overlap(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.fn_check_booking_overlap() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    cnt INT;
BEGIN
    SELECT COUNT(*) INTO cnt
    FROM Booking b
    WHERE b.room_id = NEW.room_id
      AND b.booking_id <> COALESCE(NEW.booking_id, -1)
      AND (NEW.start_date < b.end_date AND NEW.end_date > b.start_date);

    IF cnt > 0 THEN
        RAISE EXCEPTION 'Комната % уже забронирована на указанный период (найдено % перекрывающих записей)', NEW.room_id, cnt;
    END IF;
    RETURN NEW;
END;
$$;


ALTER FUNCTION public.fn_check_booking_overlap() OWNER TO postgres;

--
-- Name: fn_check_room_capacity(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.fn_check_room_capacity() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    room_cap INT;
    guests_after INT;
BEGIN
    -- узнаём вместимость через Booking->Room->RoomType
    SELECT rt.capacity INTO room_cap
    FROM Booking b
    JOIN Room r ON b.room_id = r.room_id
    JOIN RoomType rt ON r.type_id = rt.type_id
    WHERE b.booking_id = NEW.booking_id;

    IF room_cap IS NULL THEN
        RAISE EXCEPTION 'Не найдена броь или номер для booking_id=%', NEW.booking_id;
    END IF;

    SELECT COUNT(*) INTO guests_after FROM BookingGuest WHERE booking_id = NEW.booking_id;
    IF TG_OP = 'INSERT' THEN
        guests_after := guests_after + 1; -- учитываем добавляемого гостя
    END IF;

    IF guests_after > room_cap THEN
        RAISE EXCEPTION 'Превышена вместимость номера: гостей=% (вместимость=%)', guests_after, room_cap;
    END IF;

    RETURN NEW;
END;
$$;


ALTER FUNCTION public.fn_check_room_capacity() OWNER TO postgres;

--
-- Name: fn_update_room_status(integer); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.fn_update_room_status(book_id integer) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE
    rid INT;
    has_active INT;
BEGIN
    SELECT room_id INTO rid FROM Booking WHERE booking_id = book_id;
    IF rid IS NULL THEN
        RETURN;
    END IF;

    SELECT COUNT(*) INTO has_active
    FROM Booking b
    WHERE b.room_id = rid AND b.start_date <= current_date AND b.end_date > current_date;

    IF has_active > 0 THEN
        UPDATE Room SET status = 'занят' WHERE room_id = rid;
    ELSE
        UPDATE Room SET status = 'свободен' WHERE room_id = rid;
    END IF;
END;
$$;


ALTER FUNCTION public.fn_update_room_status(book_id integer) OWNER TO postgres;

--
-- Name: get_booking_guests(integer); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_booking_guests(booking_id_param integer) RETURNS TABLE(client_id integer, full_name character varying, passport_number character varying)
    LANGUAGE plpgsql STABLE
    AS $$
BEGIN
    RETURN QUERY
    SELECT c.client_id, c.full_name, c.passport_number
    FROM BookingGuest bg
    JOIN Client c ON bg.client_id = c.client_id
    WHERE bg.booking_id = booking_id_param
    ORDER BY c.client_id;
END;
$$;


ALTER FUNCTION public.get_booking_guests(booking_id_param integer) OWNER TO postgres;

--
-- Name: get_current_client_id(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_current_client_id() RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
DECLARE
    current_username VARCHAR := current_user;
    client_id_val INT;
BEGIN
    SELECT client_id INTO client_id_val 
    FROM Client 
    WHERE full_name ILIKE '%' || current_username || '%'
    LIMIT 1;
    
    RETURN client_id_val;
END;
$$;


ALTER FUNCTION public.get_current_client_id() OWNER TO postgres;

--
-- Name: tg_update_room_status_on_booking(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.tg_update_room_status_on_booking() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    PERFORM fn_update_room_status(COALESCE(NEW.booking_id, OLD.booking_id));
    RETURN COALESCE(NEW, OLD);
END;
$$;


ALTER FUNCTION public.tg_update_room_status_on_booking() OWNER TO postgres;

--
-- Name: update_room_status_on_booking(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.update_room_status_on_booking() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    -- При создании бронирования меняем статус номера на "занят"
    IF TG_OP = 'INSERT' THEN
        UPDATE Room SET status = 'занят' WHERE room_id = NEW.room_id;
    -- При удалении бронирования меняем статус обратно на "свободен"
    ELSIF TG_OP = 'DELETE' THEN
        UPDATE Room SET status = 'свободен' WHERE room_id = OLD.room_id;
    END IF;
    RETURN NEW;
END;
$$;


ALTER FUNCTION public.update_room_status_on_booking() OWNER TO postgres;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: booking; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.booking (
    booking_id integer NOT NULL,
    room_id integer NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    booking_fee numeric(10,2) NOT NULL,
    valid_from timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    valid_to timestamp without time zone,
    CONSTRAINT chk_dates CHECK ((start_date < end_date))
);


ALTER TABLE public.booking OWNER TO postgres;

--
-- Name: bookingguest; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.bookingguest (
    client_b_id integer NOT NULL,
    booking_id integer NOT NULL,
    client_id integer NOT NULL
);


ALTER TABLE public.bookingguest OWNER TO postgres;

--
-- Name: bookingservice; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.bookingservice (
    service_b_id integer NOT NULL,
    booking_id integer NOT NULL,
    service_id integer NOT NULL
);


ALTER TABLE public.bookingservice OWNER TO postgres;

--
-- Name: client; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.client (
    client_id integer NOT NULL,
    full_name character varying(100) NOT NULL,
    passport_number public.dm_passport,
    prepayment numeric(10,2) DEFAULT 0.00
);


ALTER TABLE public.client OWNER TO postgres;

--
-- Name: guest_own_data; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.guest_own_data AS
 SELECT client_id,
    full_name,
    passport_number,
    prepayment
   FROM public.client
  WHERE (client_id = public.get_current_client_id());


ALTER VIEW public.guest_own_data OWNER TO postgres;

--
-- Name: room; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.room (
    room_id integer NOT NULL,
    type_id integer NOT NULL,
    room_number character varying(10) NOT NULL,
    status character varying(20) DEFAULT 'свободен'::character varying NOT NULL,
    week_day_rate integer NOT NULL
);


ALTER TABLE public.room OWNER TO postgres;

--
-- Name: roomtype; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.roomtype (
    type_id integer NOT NULL,
    name character varying(50) NOT NULL,
    price numeric(10,2) NOT NULL,
    capacity integer NOT NULL
);


ALTER TABLE public.roomtype OWNER TO postgres;

--
-- Name: my_bookings; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.my_bookings AS
 SELECT b.booking_id,
    b.room_id,
    b.start_date,
    b.end_date,
    b.booking_fee,
    b.valid_from,
    b.valid_to,
    r.room_number,
    rt.name AS room_type
   FROM (((public.booking b
     JOIN public.bookingguest bg ON ((b.booking_id = bg.booking_id)))
     JOIN public.room r ON ((b.room_id = r.room_id)))
     JOIN public.roomtype rt ON ((r.type_id = rt.type_id)))
  WHERE (bg.client_id = public.get_current_client_id());


ALTER VIEW public.my_bookings OWNER TO postgres;

--
-- Name: service; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.service (
    service_id integer NOT NULL,
    name character varying(100) NOT NULL,
    price numeric(10,2) NOT NULL,
    description character varying(255)
);


ALTER TABLE public.service OWNER TO postgres;

--
-- Data for Name: booking; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.booking (booking_id, room_id, start_date, end_date, booking_fee, valid_from, valid_to) FROM stdin;
1	1	2025-12-18	2025-12-26	1000.00	2025-12-18 21:03:17.650193	\N
2	1	2026-12-18	2026-12-26	1000.00	2025-12-18 21:04:13.86376	\N
3	1	2025-12-18	2025-12-26	1000.00	2025-12-18 21:17:59.023944	\N
4	7	2025-12-18	2025-12-19	4000.00	2025-12-18 21:49:55.364916	\N
5	8	2025-12-23	2025-12-26	3888.50	2025-12-23 18:21:37.575533	\N
6	5	2025-12-23	2025-12-26	1000.00	2025-12-23 18:24:52.227479	\N
7	3	2025-12-23	2025-12-24	2000.00	2025-12-23 19:13:59.848061	\N
8	4	2025-12-23	2025-12-26	12000.00	2025-12-23 19:37:25.773907	\N
9	7	2025-12-23	2025-12-24	4000.00	2025-12-23 19:41:43.235289	\N
10	2	2025-12-23	2025-12-24	1000.00	2025-12-23 19:47:54.883452	\N
11	6	2025-12-23	2025-12-24	2000.00	2025-12-23 19:48:04.403192	\N
12	1	2025-12-26	2025-12-28	2000.00	2025-12-23 20:31:52.835119	\N
13	8	2025-12-27	2025-12-29	7777.00	2025-12-23 20:33:16.936085	\N
14	6	2025-12-27	2025-12-29	4000.00	2025-12-23 20:34:33.87235	\N
\.


--
-- Data for Name: bookingguest; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.bookingguest (client_b_id, booking_id, client_id) FROM stdin;
3	3	5
4	4	5
5	4	4
6	5	9
7	5	7
8	6	6
9	7	1
10	7	2
11	7	3
12	8	1
13	8	6
14	9	2
15	10	1
16	10	2
17	11	1
18	11	2
19	11	3
20	12	9
21	12	10
22	13	3
23	14	3
\.


--
-- Data for Name: bookingservice; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.bookingservice (service_b_id, booking_id, service_id) FROM stdin;
1	4	5
2	4	5
3	4	5
4	5	6
5	11	4
6	11	4
7	11	4
8	11	4
9	11	4
10	11	4
11	11	4
12	11	4
13	11	4
14	11	4
15	11	4
16	11	4
17	11	4
18	11	4
19	11	4
20	11	4
21	11	4
22	11	4
23	11	4
24	11	4
25	11	2
26	11	2
27	11	2
\.


--
-- Data for Name: client; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.client (client_id, full_name, passport_number, prepayment) FROM stdin;
1	Иванов Иван Иванович	1234 567890	5000.00
2	Петров Петр Петрович	2345 678901	3000.00
3	Сидоров Алексей Викторович	3456 789012	7000.00
4	Кузнецова Мария Сергеевна	4567 890123	0.00
5	Зубенко Михаил Петрович	1234567890	1000000.00
6	Татьяна Морская Пехота	1234098765	666.00
7	Биба	4312568790	111.00
8	Боба	0987651234	222.00
9	Жижа	1236547890	2500.00
10	Создание	1230856391	7000.00
\.


--
-- Data for Name: room; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.room (room_id, type_id, room_number, status, week_day_rate) FROM stdin;
5	1	103	занят	100
3	2	201	занят	4000
4	3	301	занят	8000
7	3	105	занят	100
2	1	102	занят	2000
1	1	101	занят	2000
8	4	501	занят	100
6	2	104	занят	100
\.


--
-- Data for Name: roomtype; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.roomtype (type_id, name, price, capacity) FROM stdin;
1	Эконом	2000.00	2
2	Стандарт	4000.00	3
3	Люкс	8000.00	4
4	ХатаСпешлЛюкс	7777.00	3
5	Тест	300.00	3
6	тест	123.00	3
\.


--
-- Data for Name: service; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.service (service_id, name, price, description) FROM stdin;
1	Завтрак	500.00	Континентальный завтрак
2	Ужин	1000.00	Трехразовое питание
3	SPA	2000.00	Спа-процедуры
4	Парковка	300.00	Охраняемая парковка
5	Коньяк	3333.00	Очень вкусно
6	Стать счастливым	666.00	А ты точно хочешь?
\.


--
-- Name: booking booking_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.booking
    ADD CONSTRAINT booking_pkey PRIMARY KEY (booking_id);


--
-- Name: bookingguest bookingguest_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.bookingguest
    ADD CONSTRAINT bookingguest_pkey PRIMARY KEY (client_b_id);


--
-- Name: bookingservice bookingservice_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.bookingservice
    ADD CONSTRAINT bookingservice_pkey PRIMARY KEY (service_b_id);


--
-- Name: client client_passport_number_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.client
    ADD CONSTRAINT client_passport_number_key UNIQUE (passport_number);


--
-- Name: client client_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.client
    ADD CONSTRAINT client_pkey PRIMARY KEY (client_id);


--
-- Name: room room_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.room
    ADD CONSTRAINT room_pkey PRIMARY KEY (room_id);


--
-- Name: room room_room_number_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.room
    ADD CONSTRAINT room_room_number_key UNIQUE (room_number);


--
-- Name: roomtype roomtype_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.roomtype
    ADD CONSTRAINT roomtype_pkey PRIMARY KEY (type_id);


--
-- Name: service service_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.service
    ADD CONSTRAINT service_pkey PRIMARY KEY (service_id);


--
-- Name: booking trg_check_booking_dates; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_check_booking_dates BEFORE INSERT OR UPDATE ON public.booking FOR EACH ROW EXECUTE FUNCTION public.check_booking_dates();


--
-- Name: bookingguest trg_check_capacity; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_check_capacity BEFORE INSERT OR UPDATE ON public.bookingguest FOR EACH ROW EXECUTE FUNCTION public.fn_check_room_capacity();


--
-- Name: booking trg_check_dates; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_check_dates BEFORE INSERT OR UPDATE ON public.booking FOR EACH ROW EXECUTE FUNCTION public.fn_check_booking_dates();


--
-- Name: booking trg_check_overlap; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_check_overlap BEFORE INSERT OR UPDATE ON public.booking FOR EACH ROW EXECUTE FUNCTION public.fn_check_booking_overlap();


--
-- Name: bookingguest trg_check_room_capacity; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_check_room_capacity AFTER INSERT OR UPDATE ON public.bookingguest FOR EACH ROW EXECUTE FUNCTION public.check_room_capacity();


--
-- Name: booking trg_set_booking_fee; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_set_booking_fee BEFORE INSERT OR UPDATE ON public.booking FOR EACH ROW WHEN ((new.booking_fee IS NULL)) EXECUTE FUNCTION public.fn_calc_booking_fee();


--
-- Name: booking trg_update_room_status; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_update_room_status AFTER INSERT OR DELETE ON public.booking FOR EACH ROW EXECUTE FUNCTION public.update_room_status_on_booking();


--
-- Name: booking booking_room_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.booking
    ADD CONSTRAINT booking_room_id_fkey FOREIGN KEY (room_id) REFERENCES public.room(room_id);


--
-- Name: bookingguest bookingguest_booking_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.bookingguest
    ADD CONSTRAINT bookingguest_booking_id_fkey FOREIGN KEY (booking_id) REFERENCES public.booking(booking_id);


--
-- Name: bookingguest bookingguest_client_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.bookingguest
    ADD CONSTRAINT bookingguest_client_id_fkey FOREIGN KEY (client_id) REFERENCES public.client(client_id);


--
-- Name: bookingservice bookingservice_booking_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.bookingservice
    ADD CONSTRAINT bookingservice_booking_id_fkey FOREIGN KEY (booking_id) REFERENCES public.booking(booking_id);


--
-- Name: bookingservice bookingservice_service_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.bookingservice
    ADD CONSTRAINT bookingservice_service_id_fkey FOREIGN KEY (service_id) REFERENCES public.service(service_id);


--
-- Name: room room_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.room
    ADD CONSTRAINT room_type_id_fkey FOREIGN KEY (type_id) REFERENCES public.roomtype(type_id);


--
-- Name: FUNCTION calc_booking_totals(booking_id_param integer); Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON FUNCTION public.calc_booking_totals(booking_id_param integer) TO manager_role;


--
-- Name: FUNCTION check_booking_dates(); Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON FUNCTION public.check_booking_dates() TO admin_role;


--
-- Name: FUNCTION check_room_capacity(); Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON FUNCTION public.check_room_capacity() TO admin_role;


--
-- Name: FUNCTION get_booking_guests(booking_id_param integer); Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON FUNCTION public.get_booking_guests(booking_id_param integer) TO admin_role;
GRANT ALL ON FUNCTION public.get_booking_guests(booking_id_param integer) TO manager_role;


--
-- Name: FUNCTION update_room_status_on_booking(); Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON FUNCTION public.update_room_status_on_booking() TO admin_role;


--
-- Name: TABLE booking; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.booking TO admin_role;
GRANT SELECT,INSERT,UPDATE ON TABLE public.booking TO manager_role;
GRANT INSERT ON TABLE public.booking TO guest_role;


--
-- Name: TABLE bookingguest; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.bookingguest TO admin_role;
GRANT SELECT,INSERT,UPDATE ON TABLE public.bookingguest TO manager_role;
GRANT INSERT ON TABLE public.bookingguest TO guest_role;


--
-- Name: TABLE bookingservice; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.bookingservice TO admin_role;
GRANT SELECT,INSERT,UPDATE ON TABLE public.bookingservice TO manager_role;


--
-- Name: TABLE client; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.client TO admin_role;
GRANT SELECT,INSERT,UPDATE ON TABLE public.client TO manager_role;
GRANT INSERT ON TABLE public.client TO guest_role;


--
-- Name: TABLE guest_own_data; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT,UPDATE ON TABLE public.guest_own_data TO guest_role;
GRANT ALL ON TABLE public.guest_own_data TO admin_role;


--
-- Name: TABLE room; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.room TO admin_role;
GRANT SELECT,INSERT,UPDATE ON TABLE public.room TO manager_role;
GRANT SELECT ON TABLE public.room TO guest_role;


--
-- Name: TABLE roomtype; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.roomtype TO admin_role;
GRANT SELECT ON TABLE public.roomtype TO manager_role;
GRANT SELECT ON TABLE public.roomtype TO guest_role;


--
-- Name: TABLE my_bookings; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT ON TABLE public.my_bookings TO guest_role;
GRANT ALL ON TABLE public.my_bookings TO admin_role;


--
-- Name: TABLE service; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.service TO admin_role;
GRANT SELECT ON TABLE public.service TO manager_role;
GRANT SELECT ON TABLE public.service TO guest_role;


--
-- PostgreSQL database dump complete
--

